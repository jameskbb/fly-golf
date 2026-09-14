"""`fly-golf train`: fit a readout of MaleCNS descending-neuron activity from practice.

Pipeline (docs/TRAINING.md, method `hindsight-gated-v2`):

1. **Situations** (`situations.py`): practice-green putts, putts on the course greens, chips and
   pitches around the greens, and full shots from tees / fairways / rough / sand. 30 % are held
   out for testing.
2. **Neural features**: for each situation, the v0.2 sensory frame is injected into the
   connectome and 400 ms of LIF dynamics are simulated, exactly as in play. Features = mean
   rate of every descending-neuron type in the readout window. The fixed v0.2 readout's
   channels (tempo, face, strike, ...) are kept too.
3. **Practice by trial and error** (hindsight targets): in the simulator, the fly "tries"
   many clubs / aims / powers from that exact spot, with its own tempo, face and strike. Each
   club's result is judged ROBUSTLY (the average over neighbouring aims and powers, so a stroke
   that only works if it is perfect, with the trees or water a hair away, scores badly), and
   among the clubs that do about as well as the best one the SHORTEST is kept: a golfer's
   "least club that gets there safely". That makes the target club a consistent function of
   the situation instead of an arbitrary pick between a soft long club and a full short one.
   Only physics outcomes are used: no analytic solution is given to anything.
4. **Fit** (all from standardised log DN-type rates): a putter gate (PCA + L2 logistic
   regression: putt or swing?), a club head for swings (PCA + ridge regression onto the club's
   position in the bag, rounded), and two ridge heads for (aim, power), one for putts and one
   for full swings, picked by the gate. PCA size and regularisation are chosen by 5-fold
   cross-validation on the training situations only; every head is collapsed to one linear
   layer on the features.
5. **Calibrate by practice** (`calibrate`): on the training situations only, the fitted readout
   plays its own strokes; a stretch and shift of the club head's output (undoing ridge shrinkage,
   and preferring the shorter club when a long miss would fly into the trees) and a power scale
   per head are chosen to maximise the practice score, but only among settings that make no kind
   of shot more than 1 m worse. The identity is always in the grid; the held-out evaluation also
   reports the uncalibrated readouts.
6. **Evaluate** on the held-out situations with the real physics, against: the fixed v0.2
   readout (untrained), a *no-brain* readout fitted the same way directly on the 14 sensory
   channels, the mock heuristic, the trial-and-error best (an upper bound), and optionally the
   same pipeline on a degree-preserving *shuffled* connectome (`--control shuffled`).
   Closed-loop rounds are measured separately with `fly-golf bench`.
"""

from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..brain.interfaces import MotorCommand, SensoryFrame
from ..brain.malecns.controller import FEATURE_SPACE, FEATURE_SPACE_SIDE, FEATURE_SPACES, MaleCNSController
from ..brain.malecns.engine import ENGINE_VERSION
from ..brain.malecns.graph import CompiledGraph
from ..brain.mock import MockBrainController
from ..brain.motor import MotorDecoderV2
from ..brain.sensory import ProxySensoryEncoderV2
from ..brain.trained import (
    HEADS,
    LEGACY_ENGINE_VERSION,
    OUTPUTS,
    GatedReadout,
    Readout,
    feature_transform,
    sigmoid,
    swing_club_index,
    trained_channels,
)
from ..golf.clubs import BAG, CLUB_BY_ID, PUTTER, reach_for
from ..golf.course_env import apply_lie
from ..golf.env import PuttingEnvironment
from ..golf.flight import Outcome, simulate_shot
from ..golf.physics import Outcome as PuttOutcome
from ..golf.physics import simulate_roll
from ..provenance import git_info, versions
from .situations import SITUATIONS_VERSION, Situation, generate_situations

TRAINING_VERSION = "hindsight-gated-v2"
DECISION_WINDOW_MS = 400.0
PENALTY_M = 25.0  # a penalty stroke is worth this many metres of leave in the practice score
FULL_AIM_RANGE = 0.4  # full-shot practice tries aims within +-0.4 x 25 deg = +-10 deg of the body heading
FULL_AIMS = 9
FULL_POWERS = 11
ROBUST_TOL_M = 2.0  # a club is "about as good" as the best if its robust score is within
ROBUST_TOL_FRAC = 0.04  # max(2 m, 4 % of the distance to the pin) of the best club's
CV_FOLDS = 5
PCA_CHOICES = (4, 8, 16, 32, 64, 128, 256)  # CV picks one; 128/256 pay off from ~1,300 swing examples
ALPHA_CHOICES = (0.1, 1.0, 10.0, 100.0, 1000.0)
CAL_STRETCH = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)  # decoding calibration grid (step 5)
CAL_SHIFT = (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5)
CAL_POWER = (0.8, 0.85, 0.9, 0.95, 1.05, 1.1)
CAL_MAX_KIND_DROP_M = 1.0  # calibration may not make any kind of shot this much worse in practice
GATE_L2_CHOICES = (0.001, 0.01, 0.1, 1.0)
GATE_NEWTON_STEPS = 30
KINDS = ("putt", "green", "short", "full")
NEUTRAL = {"stroke_tempo": 0.5, "face_open": 0.0, "face_closed": 0.0, "strike": 1.0}
NEUTRAL_FULL = NEUTRAL | {"aim_left": 0.0, "aim_right": 0.0, "stroke_power": 0.5, "club_reach": 0.5}

_DECODER = MotorDecoderV2()
_ENCODER = ProxySensoryEncoderV2()
_GRAPH: CompiledGraph | None = None  # set in the parent before forking workers
_CTRL: MaleCNSController | None = None


# ------------------------------------------------------------------------------------ graph
def shuffled_graph(graph: CompiledGraph, seed: int) -> CompiledGraph:
    """Degree-preserving control: every edge keeps its source neuron and weight (so each
    neuron's out-degree, sign and synapse counts are unchanged) but gets a random target drawn
    from the multiset of all targets (so every neuron's in-degree is unchanged too)."""
    rng = np.random.default_rng(seed)
    post = np.asarray(graph.post)[rng.permutation(len(graph.post))]
    manifest = dict(graph.manifest) | {"control": f"shuffled-targets seed={seed}"}
    return CompiledGraph(
        graph.ptr, np.ascontiguousarray(post), graph.weight, graph.ids, graph.neurons, manifest, graph.path
    )


# ------------------------------------------------------------------------------ one situation
def play_once(sit: Situation, channels: dict[str, float], env=None) -> dict:
    """Decode `channels` into a stroke at `sit` and play it once with the real physics."""
    env = env or sit.build()
    cmd = MotorCommand(channels=channels, source="training")
    if isinstance(env, PuttingEnvironment):
        sw = _DECODER.decode(cmd, env.body_heading, forced_club=PUTTER)
        sc = env.scenario
        roll = simulate_roll(sc.green, env.ball, sc.cup, sw.stroke)
        holed = roll.outcome is PuttOutcome.HOLED
        leave = 0.0 if holed else math.hypot(roll.final_position[0] - sc.cup[0], roll.final_position[1] - sc.cup[1])
        return {
            "holed": holed,
            "leave_m": leave,
            "penalty": 0,
            "outcome": roll.outcome.value,
            "club": PUTTER.id,
            "score": 1.0 if holed else -leave,
        }
    sw = _DECODER.decode(cmd, env.body_heading)
    res = simulate_shot(env.hole, env.ball, apply_lie(sw.launch, env.lie))
    cx, cy = env.hole.cup
    holed = res.outcome is Outcome.HOLED
    penalty = int(res.outcome in (Outcome.WATER, Outcome.OUT_OF_BOUNDS))
    fx, fy = env.ball if res.outcome is Outcome.OUT_OF_BOUNDS else res.final_position
    leave = 0.0 if holed else math.hypot(cx - fx, cy - fy)
    score = 1.0 if holed else -leave - PENALTY_M * penalty
    return {
        "holed": holed,
        "leave_m": leave,
        "penalty": penalty,
        "outcome": res.outcome.value,
        "club": sw.club.id,
        "score": score,
    }


def _with(fixed: dict[str, float], aim: float, power: float, reach: float) -> dict[str, float]:
    return trained_channels(fixed, {"aim": aim, "stroke_power": power, "club_reach": reach})


def _smooth(grid: np.ndarray) -> np.ndarray:
    """3x3 neighbourhood mean (edges padded): how good a stroke is if it comes off a little off."""
    p = np.pad(grid, 1, mode="edge")
    return (
        sum(
            p[1 + di : 1 + di + grid.shape[0], 1 + dj : 1 + dj + grid.shape[1]]
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
        )
        / 9.0
    )


def _smooth_argmax(grid: np.ndarray) -> tuple[int, int]:
    """Argmax of the neighbourhood mean: prefer the middle of a good region (robust target)."""
    i, j = np.unravel_index(int(np.argmax(_smooth(grid))), grid.shape)
    return int(i), int(j)


def choose_club(per_club: list[tuple[float, int]], distance_m: float) -> int:
    """Given (robust score, bag index) for every club, the shortest club whose robust score is
    within max(ROBUST_TOL_M, ROBUST_TOL_FRAC x distance) of the best one."""
    best = max(s for s, _ in per_club)
    tol = max(ROBUST_TOL_M, ROBUST_TOL_FRAC * distance_m)
    return min(k for s, k in per_club if s >= best - tol)


def practice(sit: Situation, fixed: dict[str, float], env=None) -> dict:
    """Trial-and-error search for the best (club, aim, power) from this spot, given the fly's
    own fixed tempo / face / strike. Returns the target plus how good it was."""
    env = env or sit.build()
    putting = isinstance(env, PuttingEnvironment) or env.on_putting_surface
    if putting:
        reach = reach_for(PUTTER)

        def search(aims, powers):
            grid = np.array([[play_once(sit, _with(fixed, a, p, reach), env)["score"] for p in powers] for a in aims])
            i, j = _smooth_argmax(grid)
            return aims[i], powers[j]

        a0, p0 = search(np.linspace(-1.0, 1.0, 41), np.linspace(0.0, 1.0, 31))
        a1, p1 = search(
            np.clip(np.linspace(a0 - 0.05, a0 + 0.05, 11), -1, 1),
            np.clip(np.linspace(p0 - 0.034, p0 + 0.034, 11), 0, 1),
        )
        best = {"aim": float(a1), "stroke_power": float(p1), "club_reach": reach, "club": PUTTER.id}
    else:
        # Every club x swing length x aim within +-10 deg of where the fly faces (it addresses
        # its target within +-6 deg, plus face effects). No observation is consulted: the
        # distance below only sets how close to the best club counts as "about as good".
        aims = np.linspace(-FULL_AIM_RANGE, FULL_AIM_RANGE, FULL_AIMS)
        powers = np.linspace(0.0, 1.0, FULL_POWERS)
        per_club: list[tuple[float, int]] = []
        spots: dict[int, tuple[float, float]] = {}
        for k, club in enumerate(BAG):
            r = reach_for(club)
            grid = np.array(
                [[play_once(sit, _with(fixed, float(a), float(p), r), env)["score"] for p in powers] for a in aims]
            )
            sm = _smooth(grid)
            i, j = np.unravel_index(int(np.argmax(sm)), sm.shape)
            per_club.append((float(sm[i, j]), k))
            spots[k] = (float(aims[i]), float(powers[j]))
        cx, cy = env.hole.cup
        k = choose_club(per_club, math.hypot(cx - env.ball[0], cy - env.ball[1]))
        club = BAG[k]
        r = reach_for(club)
        a0, p0 = spots[k]
        aims = np.clip(a0 + np.linspace(-0.05, 0.05, 7), -1, 1)
        pws = np.clip(p0 + np.linspace(-0.05, 0.05, 5), 0, 1)
        grid = np.array([[play_once(sit, _with(fixed, a, p, r), env)["score"] for p in pws] for a in aims])
        i, j = _smooth_argmax(grid)
        best = {"aim": float(aims[i]), "stroke_power": float(pws[j]), "club_reach": r, "club": club.id}
    result = play_once(sit, _with(fixed, best["aim"], best["stroke_power"], best["club_reach"]), env)
    return {"target": best, "result": result}


# --------------------------------------------------------------------------------- workers
def _init_worker() -> None:
    global _CTRL
    _CTRL = MaleCNSController(_GRAPH)


def _run_situation(sit_dict: dict) -> dict:
    sit = Situation.from_dict(sit_dict)
    env = sit.build()
    obs = env.observe()
    frame = _ENCODER.encode(obs)
    _CTRL.reset(0)
    _CTRL.observe(frame)
    _CTRL.step(DECISION_WINDOW_MS)
    fixed = dict(_CTRL.last_fixed_channels())
    search = practice(sit, fixed, env)
    # The no-brain baseline plays with a neutral tempo/face/strike, so it practises with them too.
    neutral = practice(sit, NEUTRAL_FULL, env)
    return {
        "index": sit.index,
        "features": _CTRL.last_features().tolist(),
        "features_side": _CTRL.last_features(FEATURE_SPACE_SIDE).tolist(),
        "fixed": fixed,
        "sensory": dict(frame.channels),
        "target": search["target"],
        "best": search["result"],
        "target_no_brain": neutral["target"],
        "best_no_brain": neutral["result"],
        "distance_to_pin_m": obs.distance_to_pin_m if obs.distance_to_pin_m is not None else obs.distance_m,
    }


def collect(
    graph: CompiledGraph, situations: list[Situation], jobs: int = 1, progress: Callable[[int, int], None] | None = None
) -> tuple[dict[str, list[str]], list[dict]]:
    """Neural features (every feature space) + fixed channels + practice targets for every situation."""
    global _GRAPH
    _GRAPH = graph
    ctrl = MaleCNSController(graph)
    names = {space: ctrl.feature_names_for(space) for space in FEATURE_SPACES}
    todo = [s.to_dict() for s in situations]
    out: list[dict] = []
    if jobs <= 1:
        _init_worker()
        for k, sd in enumerate(todo):
            out.append(_run_situation(sd))
            if progress:
                progress(k + 1, len(todo))
    else:
        ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")
        with ctx.Pool(jobs, initializer=_init_worker) as pool:
            for k, r in enumerate(pool.imap_unordered(_run_situation, todo, chunksize=2)):
                out.append(r)
                if progress:
                    progress(k + 1, len(todo))
    out.sort(key=lambda r: r["index"])
    return names, out


# ------------------------------------------------------------------------------------- fit
def _standardise(x: np.ndarray, transform: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xt = feature_transform(x) if transform == "log1p" else np.asarray(x, dtype=np.float64)
    mean = xt.mean(axis=0)
    scale = xt.std(axis=0)
    scale[scale < 1e-9] = 1.0
    return (xt - mean) / scale, mean, scale


def _folds(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).permutation(n) % CV_FOLDS


def _stratified_folds(labels: np.ndarray, seed: int) -> np.ndarray:
    """Fold ids with every class spread evenly over the folds (so no training fold is one class)."""
    rng = np.random.default_rng(seed)
    folds = np.empty(len(labels), dtype=int)
    for c in np.unique(labels):
        idx = np.flatnonzero(labels == c)
        folds[rng.permutation(idx)] = np.arange(len(idx)) % CV_FOLDS
    return folds


def _k_choices(max_k: int) -> list[int]:
    """PCA sizes to try: the standard ones that fit, plus the full width when that is smaller than
    the largest (v1 bug: a 14-channel input could only ever use 4 or 8 of its 14 directions)."""
    ks = [k for k in PCA_CHOICES if k < max_k]
    top = min(max_k, PCA_CHOICES[-1])
    return ks if top in ks else [*ks, top]


def _pca(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(centre, principal axes) of z; axes are rows, strongest first."""
    zm = z.mean(axis=0)
    _, _, vt = np.linalg.svd(z - zm, full_matrices=False)
    return zm, vt


def _ridge(z: np.ndarray, y: np.ndarray, k: int, alpha: float, basis=None) -> tuple[np.ndarray, np.ndarray]:
    """PCA(k) + ridge, collapsed to (W [outputs x features], b) on the standardised input z."""
    zm, vt = basis or _pca(z)
    comps = vt[: min(k, vt.shape[0])]
    p = (z - zm) @ comps.T
    ym = y.mean(axis=0)
    coef = np.linalg.solve(p.T @ p + alpha * np.eye(p.shape[1]), p.T @ (y - ym))  # [k x outputs]
    w = (comps.T @ coef).T
    return w, ym - w @ zm


def fit_ridge_cv(z: np.ndarray, y: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray, dict]:
    n = len(z)
    folds = _folds(n, seed)
    ystd = y.std(axis=0)
    ystd[ystd < 1e-9] = 1.0
    bases = [_pca(z[folds != f]) for f in range(CV_FOLDS)]
    max_k = min(z.shape)
    best, table = None, []
    for k in _k_choices(max_k):
        for alpha in ALPHA_CHOICES:
            err = 0.0
            for f in range(CV_FOLDS):
                tr, va = folds != f, folds == f
                w, b = _ridge(z[tr], y[tr], k, alpha, bases[f])
                err += float((((z[va] @ w.T + b - y[va]) / ystd) ** 2).sum())
            err /= n
            table.append({"pca": k, "alpha": alpha, "cv_mse": round(err, 6)})
            if best is None or err < best[0]:
                best = (err, k, alpha)
    err, k, alpha = best
    w, b = _ridge(z, y, k, alpha)
    return w, b, {"pca": k, "alpha": alpha, "cv_mse": round(err, 6), "n": n, "grid": table}


def _logistic(p: np.ndarray, y: np.ndarray, lam: float) -> tuple[np.ndarray, float]:
    """L2-regularised logistic regression by Newton's method (IRLS); exact, converges in a few steps."""
    n, k = p.shape
    x = np.column_stack([p, np.ones(n)])
    reg = lam * np.eye(k + 1)
    reg[-1, -1] = 1e-6  # (almost) no penalty on the intercept
    w = np.zeros(k + 1)
    for _ in range(GATE_NEWTON_STEPS):
        mu = sigmoid(x @ w)
        grad = x.T @ (mu - y) / n + reg @ w
        hess = (x.T * (mu * (1.0 - mu))) @ x / n + reg
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w[:-1], float(w[-1])


def _gate(z: np.ndarray, y: np.ndarray, k: int, lam: float, basis=None) -> tuple[np.ndarray, float]:
    """PCA(k) + whitening + logistic regression, collapsed to logit = w . z + b."""
    zm, vt = basis or _pca(z)
    comps = vt[: min(k, vt.shape[0])]
    p = (z - zm) @ comps.T
    sd = p.std(axis=0)
    sd[sd < 1e-9] = 1.0
    a, c = _logistic(p / sd, y, lam)
    w = comps.T @ (a / sd)
    return w, c - float(w @ zm)


def fit_gate_cv(z: np.ndarray, putt: np.ndarray, seed: int = 0) -> tuple[np.ndarray, float, dict]:
    """Putter-vs-swing gate. PCA size and L2 by 5-fold CV on the error rate (log-loss tie-break)."""
    n = len(z)
    y = np.asarray(putt, dtype=np.float64)
    minority = int(min(y.sum(), n - y.sum()))
    if minority < CV_FOLDS:  # (almost) all one kind: a constant gate
        return np.zeros(z.shape[1]), (8.0 if y.mean() >= 0.5 else -8.0), {"constant": True, "n": n}
    folds = _stratified_folds(y >= 0.5, seed + 1)
    bases = [_pca(z[folds != f]) for f in range(CV_FOLDS)]
    max_k = min(z.shape)
    best, table = None, []
    for k in _k_choices(max_k):
        for lam in GATE_L2_CHOICES:
            wrong = loss = 0.0
            for f in range(CV_FOLDS):
                tr, va = folds != f, folds == f
                w, b = _gate(z[tr], y[tr], k, lam, bases[f])
                pr = np.clip(sigmoid(z[va] @ w + b), 1e-12, 1 - 1e-12)
                wrong += float(((pr >= 0.5) != (y[va] >= 0.5)).sum())
                loss -= float((y[va] * np.log(pr) + (1 - y[va]) * np.log(1 - pr)).sum())
            wrong, loss = wrong / n, loss / n
            table.append({"pca": k, "l2": lam, "cv_error": round(wrong, 4), "cv_logloss": round(loss, 4)})
            key = wrong + 0.01 * loss
            if best is None or key < best[0]:
                best = (key, k, lam, wrong, loss)
    _, k, lam, wrong, loss = best
    w, b = _gate(z, y, k, lam)
    return w, b, {"pca": k, "l2": lam, "cv_error": round(wrong, 4), "cv_logloss": round(loss, 4), "n": n, "grid": table}


def fit_gated_readout(
    x: np.ndarray,
    aim_power: np.ndarray,
    clubs: np.ndarray,
    names: list[str],
    transform: str = "log1p",
    seed: int = 0,
) -> tuple[GatedReadout, dict]:
    """Putter gate + swing club head + putter / full-swing (aim, power) heads, all on z(x)."""
    z, mean, scale = _standardise(x, transform)
    clubs = np.asarray(clubs, dtype=int)
    gw, gb, gate_info = fit_gate_cv(z, clubs == 0, seed)
    swing = clubs > 0
    rows = swing if swing.sum() >= 4 * CV_FOLDS else np.ones(len(z), dtype=bool)
    cw, cb, club_info = fit_ridge_cv(z[rows], clubs[rows, None].astype(np.float64), seed)
    off = np.abs(swing_club_index(z[rows] @ cw[0] + cb[0]) - clubs[rows])
    club_info["train_clubs_off"] = round(float(off.mean()), 4)
    head_w, head_b, head_info = {}, {}, {}
    for head in HEADS:
        mask = clubs == 0 if head == "putter" else swing
        if mask.sum() < 4 * CV_FOLDS:  # too few examples of this kind: share every example
            mask = np.ones(len(z), dtype=bool)
        w, b, info = fit_ridge_cv(z[mask], aim_power[mask], seed)
        head_w[head], head_b[head], head_info[head] = w, b, info
    readout = GatedReadout(list(names), mean, scale, gw, gb, cw[0], float(cb[0]), head_w, head_b, transform=transform)
    return readout, {"gate": gate_info, "club": club_info, "heads": head_info}


def _brief(fit: dict) -> dict:
    """The CV choices without the full grids (for readout metadata)."""
    return {
        "gate": {k: v for k, v in fit["gate"].items() if k != "grid"},
        "club": {k: v for k, v in fit["club"].items() if k != "grid"},
        "heads": {h: {k: v for k, v in i.items() if k != "grid"} for h, i in fit["heads"].items()},
        "calibration": {k: v for k, v in (fit.get("calibration") or {}).items() if k != "grid"},
    }


def calibrate(readout: GatedReadout, examples: list[tuple]) -> tuple[GatedReadout, dict]:
    """Step 5: tune how the readout's outputs are DECODED, by practising with the readout itself.

    `examples` are TRAINING situations only: (situation, environment, input vector, fixed channels,
    scoring readout). The scoring readout is one fitted WITHOUT that situation (out-of-fold), so the
    decoding is tuned on predictions as noisy as they will be on shots the readout has never seen.
    (Tuning it on the final readout's own training predictions, which fit better than unseen ones,
    over-stretched the club head and made held-out full shots worse.) The chosen settings are then
    applied to `readout`, the readout fitted on all training situations.

    Each example is played with the real physics; the club head's output is stretched about its
    mean (undoing the ridge regression's shrinkage toward the middle of the bag) and shifted (a
    miss that is a club long can fly the green into the trees, one that is short cannot), and each
    head's power is scaled. The grid always contains the identity. A setting is only allowed if NO
    kind of shot (putt / green / short / full) gets more than CAL_MAX_KIND_DROP_M worse in practice
    than with the identity: a pooled score must not buy chips at the cost of drives. Nothing here
    changes what the readout reads: still only its input vector."""
    zs = [ro.z(x) for _, _, x, _, ro in examples]
    swing = [i for i, z in enumerate(zs) if sigmoid(examples[i][4].gate_weights @ z + examples[i][4].gate_bias) < 0.5]
    swing_set = set(swing)
    putt = [i for i in range(len(examples)) if i not in swing_set]
    center = float(np.mean([examples[i][4].club_raw(zs[i]) for i in swing])) if swing else 7.0
    params: dict = {
        "club_center": center,
        "club_stretch": 1.0,
        "club_shift": 0.0,
        "power_scale": {h: 1.0 for h in HEADS},
    }

    def scores(p: dict, idx: list[int]) -> tuple[float, dict[str, float]]:
        """(pooled mean practice score, mean per kind of situation) over `idx` with decoding `p`."""
        per: dict[str, list[float]] = {}
        for i in idx:
            sit, env, x, fixed, ro = examples[i]
            stroke = trained_channels(fixed, replace(ro, **p).predict(x))
            per.setdefault(sit.kind, []).append(play_once(sit, stroke, env)["score"])
        pooled = float(np.mean([s for v in per.values() for s in v])) if idx else 0.0
        return pooled, {k: float(np.mean(v)) for k, v in per.items()}

    def allowed(per: dict[str, float], base: dict[str, float]) -> bool:
        return all(per[k] >= base[k] - CAL_MAX_KIND_DROP_M for k in base)

    before = {"swing": scores(params, swing), "putter": scores(params, putt)}
    grid = []
    best = (before["swing"][0], 1.0, 0.0)
    for stretch in CAL_STRETCH:
        for shift in CAL_SHIFT:
            pooled, per = scores(params | {"club_stretch": stretch, "club_shift": shift}, swing)
            ok = allowed(per, before["swing"][1])
            grid.append({"stretch": stretch, "shift": shift, "score": round(pooled, 4), "allowed": ok})
            if ok and pooled > best[0] + 1e-9:
                best = (pooled, stretch, shift)
    params |= {"club_stretch": best[1], "club_shift": best[2]}
    scales = dict(params["power_scale"])
    for head, idx in (("swing", swing), ("putter", putt)):
        base_pooled, base_per = scores(params, idx)
        top = (base_pooled, 1.0)
        for k in CAL_POWER:
            pooled, per = scores(params | {"power_scale": scales | {head: k}}, idx)
            if allowed(per, base_per) and pooled > top[0] + 1e-9:
                top = (pooled, k)
        scales[head] = top[1]
    params["power_scale"] = scales
    after = {"swing": scores(params, swing), "putter": scores(params, putt)}
    readout = replace(readout, **params)
    # Settings on the edge of their grid (the best value may lie beyond it): reported, not hidden.
    edges = []
    if readout.club_stretch == max(CAL_STRETCH):
        edges.append("club_stretch")
    if readout.club_shift in (min(CAL_SHIFT), max(CAL_SHIFT)):
        edges.append("club_shift")
    edges += [f"power_scale.{h}" for h in HEADS if scales[h] in (min(CAL_POWER), max(CAL_POWER))]

    def rounded(s: tuple[float, dict[str, float]]) -> dict:
        return {"pooled": round(s[0], 3), **{k: round(v, 3) for k, v in sorted(s[1].items())}}

    return readout, {
        "club_center": round(readout.club_center, 4),
        "club_stretch": readout.club_stretch,
        "club_shift": readout.club_shift,
        "power_scale": scales,
        "max_kind_drop_m": CAL_MAX_KIND_DROP_M,
        "scored_out_of_fold": True,
        "at_grid_edge": edges,
        "n_swing": len(swing),
        "n_putt": len(putt),
        "practice_score_before": {h: rounded(before[h]) for h in ("swing", "putter")},
        "practice_score_after": {h: rounded(after[h]) for h in ("swing", "putter")},
        "grid": grid,
    }


# -------------------------------------------------------------------------------- evaluate
def _summary(results: list[dict], kinds: list[str], target_clubs: list[str]) -> dict:
    out = {}
    order = {c.id: i for i, c in enumerate(BAG)}
    for kind in KINDS:
        rs = [(r, t) for r, k, t in zip(results, kinds, target_clubs, strict=True) if k == kind]
        if not rs:
            continue
        leaves = np.array([r["leave_m"] for r, _ in rs])
        off = np.array([abs(order[r["club"]] - order[t]) for r, t in rs])
        out[kind] = {
            "n": len(rs),
            "holed_pct": round(100.0 * sum(r["holed"] for r, _ in rs) / len(rs), 1),
            "median_leave_m": round(float(np.median(leaves)), 3),
            "mean_leave_m": round(float(leaves.mean()), 3),
            "penalty_pct": round(100.0 * sum(r["penalty"] for r, _ in rs) / len(rs), 1),
            "trees_pct": round(100.0 * sum(r.get("outcome") == "out_of_bounds" for r, _ in rs) / len(rs), 1),
            "club_exact_pct": round(100.0 * float((off == 0).mean()), 1),
            "club_within1_pct": round(100.0 * float((off <= 1).mean()), 1),
        }
    return out


def evaluate(
    situations: list[Situation], rows: list[dict], readouts: dict[str, Readout | None], feature_key: str = "features"
) -> dict:
    """Held-out comparison of every variant (one stroke per situation, real physics). Club
    accuracy is measured against the (brain) practice target's club."""
    test = [(s, r) for s, r in zip(situations, rows, strict=True) if s.is_test]
    kinds = [s.kind for s, _ in test]
    targets = [r["target"]["club"] for _, r in test]
    report: dict[str, dict] = {}

    def run(name: str, channels_for: Callable[[Situation, dict], dict]) -> None:
        report[name] = _summary([play_once(s, channels_for(s, r)) for s, r in test], kinds, targets)

    run("fixed_v0.2_readout", lambda s, r: r["fixed"])

    def brain_variant(name: str, ro: Readout) -> None:
        run(name, lambda s, r: trained_channels(r["fixed"], ro.predict(np.asarray(r[feature_key]))))

    def senses_variant(name: str, ro: Readout) -> None:
        run(
            name,
            lambda s, r: trained_channels(
                r["fixed"] | NEUTRAL, ro.predict(np.asarray([r["sensory"][c] for c in ro.feature_names]))
            ),
        )

    for name, key, variant in (
        ("trained_readout", "trained", brain_variant),
        ("trained_readout_uncalibrated", "trained_uncalibrated", brain_variant),
        ("no_brain_sensory_readout", "no_brain", senses_variant),
        ("no_brain_uncalibrated", "no_brain_uncalibrated", senses_variant),
    ):
        if readouts.get(key) is not None:
            variant(name, readouts[key])

    def mock_channels(s: Situation, r: dict) -> dict:
        m = MockBrainController()
        m.reset(s.index)
        m.observe(SensoryFrame(channels=r["sensory"], encoder="proxy-v0", version="proxy-sensory-v0.2"))
        m.step(DECISION_WINDOW_MS)
        return dict(m.motor_output().channels)

    run("mock_heuristic", mock_channels)
    if all(r.get("best") is not None for _, r in test):  # (a refit carries it over from its source)
        report["practice_best_upper_bound"] = _summary([r["best"] for _, r in test], kinds, targets)
    return {"variants": report, "n_test": len(test)}


# --------------------------------------------------------------------------------- driver
def _club_index(target: dict) -> int:
    return BAG.index(CLUB_BY_ID[target["club"]])


def train(
    graph: CompiledGraph,
    out_dir: Path,
    n_putt: int = 120,
    n_green: int = 120,
    n_full: int = 200,
    seed: int = 0,
    jobs: int = 1,
    control: str | None = None,
    log: Callable[[str], None] = print,
    n_short: int = 120,
    feature_space: str = FEATURE_SPACE,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    if control == "shuffled":
        graph = shuffled_graph(graph, seed=seed + 1)
    elif control is not None:
        raise ValueError(f"unknown control {control!r}")
    situations = generate_situations(n_putt, n_green, n_full, seed, n_short=n_short)
    log(f"{len(situations)} practice situations ({sum(s.is_test for s in situations)} held out); jobs={jobs}")

    def progress(k: int, n: int) -> None:
        if k == n or k % max(1, n // 20) == 0:
            log(f"  simulated + practised {k}/{n}  ({time.perf_counter() - t0:.0f} s)")

    names, rows = collect(graph, situations, jobs=jobs, progress=progress)
    graph_meta = {
        "release": graph.manifest.get("release"),
        "neurons": graph.n,
        "edges": graph.edges,
        "control": control,
        "neural_engine": ENGINE_VERSION,
    }
    counts = {"putt": n_putt, "green": n_green, "short": n_short, "full": n_full, "seed": seed}
    return fit_and_report(
        situations, rows, names, out_dir, seed, graph_meta, counts, log=log, t0=t0, feature_space=feature_space
    )


def fit_and_report(
    situations: list[Situation],
    rows: list[dict],
    names: dict[str, list[str]],
    out_dir: Path,
    seed: int,
    graph_meta: dict,
    counts: dict,
    log: Callable[[str], None] = print,
    t0: float | None = None,
    extra_meta: dict | None = None,
    upper_bound: dict | None = None,
    feature_space: str = FEATURE_SPACE,
) -> dict:
    """Steps 4-6 from collected practice rows: fit, calibrate (out of fold), evaluate, save.
    `names` maps each feature space to its feature names; `feature_space` is the one fitted."""
    t0 = time.perf_counter() if t0 is None else t0
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    control = graph_meta.get("control")
    train_idx = [i for i, s in enumerate(situations) if not s.is_test]
    if feature_space not in FEATURE_SPACES:
        raise ValueError(f"unknown feature space {feature_space!r} (known: {FEATURE_SPACES})")
    fkey = "features_side" if feature_space == FEATURE_SPACE_SIDE else "features"
    if fkey not in rows[0] or feature_space not in names:
        raise ValueError(f"these practice rows carry no {feature_space!r} features")

    def targets(key: str) -> tuple[np.ndarray, np.ndarray]:
        ap = np.asarray([[rows[i][key]["aim"], rows[i][key]["stroke_power"]] for i in train_idx])
        return ap, np.asarray([_club_index(rows[i][key]) for i in train_idx])

    log(f"fitting the brain readout on {feature_space} rates (putter gate + club head + putter / swing heads)...")
    x = np.asarray([rows[i][fkey] for i in train_idx])
    brain, brain_fit = fit_gated_readout(x, *targets("target"), names[feature_space], seed=seed)
    brain.feature_space = feature_space
    log("fitting the no-brain baseline...")
    sensory_names = list(rows[0]["sensory"])
    xs = np.asarray([[rows[i]["sensory"][c] for c in sensory_names] for i in train_idx])
    senses, senses_fit = fit_gated_readout(xs, *targets("target_no_brain"), sensory_names, transform="none", seed=seed)
    # The uncalibrated readouts are evaluated too, so the report shows what calibration bought.
    uncalibrated = {
        "trained_uncalibrated": GatedReadout.from_json(brain.to_json()),
        "no_brain_uncalibrated": GatedReadout.from_json(senses.to_json()),
    }
    log("calibrating the decoding by practice, scored out of fold (training situations only)...")
    envs = {i: situations[i].build() for i in train_idx}
    folds = _folds(len(train_idx), seed + 7)

    def out_of_fold(xx: np.ndarray, key: str, feature_names: list[str], transform: str) -> list[GatedReadout]:
        """For each training situation, a readout fitted on the other folds only."""
        ap, clubs = targets(key)
        per: list[GatedReadout | None] = [None] * len(train_idx)
        for f in range(CV_FOLDS):
            keep = folds != f
            ro, _ = fit_gated_readout(xx[keep], ap[keep], clubs[keep], feature_names, transform=transform, seed=seed)
            for j in np.flatnonzero(~keep):
                per[j] = ro
        return per

    oof_brain = out_of_fold(x, "target", names[feature_space], "log1p")
    oof_senses = out_of_fold(xs, "target_no_brain", sensory_names, "none")
    brain, brain_fit["calibration"] = calibrate(
        brain, [(situations[i], envs[i], x[j], rows[i]["fixed"], oof_brain[j]) for j, i in enumerate(train_idx)]
    )
    senses, senses_fit["calibration"] = calibrate(
        senses,
        [(situations[i], envs[i], xs[j], rows[i]["fixed"] | NEUTRAL, oof_senses[j]) for j, i in enumerate(train_idx)],
    )
    # Evaluate exactly what gets saved and installed (weights rounded to 9 decimals in the JSON).
    brain = GatedReadout.from_json(brain.to_json())
    senses = GatedReadout.from_json(senses.to_json())
    evaluation = evaluate(situations, rows, {"trained": brain, "no_brain": senses, **uncalibrated}, feature_key=fkey)
    if upper_bound is not None:
        evaluation["variants"].setdefault("practice_best_upper_bound", upper_bound)
    for name, fit in (("brain", brain_fit), ("no-brain", senses_fit)):
        if fit["calibration"]["at_grid_edge"]:
            log(f"note: {name} calibration chose a grid edge for {fit['calibration']['at_grid_edge']}")

    extra_meta = extra_meta or {}
    stamp = ("-shuffled" if control else "") + ("-refit" if "refit_from" in extra_meta else "")
    meta = {
        "training_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + stamp,
        "method": TRAINING_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "git": git_info(),
        "versions": versions() | {"situations": SITUATIONS_VERSION},
        "graph": graph_meta,
        # the engine whose activity these weights read; a refit keeps its source run's engine
        "neural_engine": graph_meta.get("neural_engine") or LEGACY_ENGINE_VERSION,
        "feature_space": feature_space,
        "situations": counts | {"train": len(train_idx), "test": evaluation["n_test"]},
        "decision_window_ms": DECISION_WINDOW_MS,
        "fit": _brief(brain_fit),
        "test_summary": evaluation["variants"].get("trained_readout"),
        "outputs": list(OUTPUTS),
    } | extra_meta
    brain.meta = meta
    brain.save(out_dir / "readout.json")
    senses.meta = meta | {"feature_space": "sensory channels (no brain)", "fit": _brief(senses_fit)}
    senses.save(out_dir / "no_brain_readout.json")
    by_side = "features_side" in rows[0] and FEATURE_SPACE_SIDE in names
    np.savez_compressed(
        out_dir / "features.npz",
        features=np.asarray([r["features"] for r in rows]),
        feature_names=np.asarray(names[FEATURE_SPACE]),
        **(
            {
                "features_side": np.asarray([r["features_side"] for r in rows]),
                "feature_names_side": np.asarray(names[FEATURE_SPACE_SIDE]),
            }
            if by_side
            else {}
        ),
        targets=np.asarray([[r["target"][o] for o in OUTPUTS] for r in rows]),
        target_club=np.asarray([_club_index(r["target"]) for r in rows]),
        targets_no_brain=np.asarray([[r["target_no_brain"][o] for o in OUTPUTS] for r in rows]),
        target_club_no_brain=np.asarray([_club_index(r["target_no_brain"]) for r in rows]),
        sensory=np.asarray([[r["sensory"][c] for c in sensory_names] for r in rows]),
        distance_to_pin_m=np.asarray([r["distance_to_pin_m"] for r in rows]),
        fixed=np.asarray([[r["fixed"][c] for c in sorted(rows[0]["fixed"])] for r in rows]),
        fixed_channels=np.asarray(sorted(rows[0]["fixed"])),
        is_test=np.asarray([s.is_test for s in situations]),
    )
    report = {
        "meta": meta,
        "fit": {"brain": brain_fit, "no_brain": senses_fit},
        "evaluation": evaluation,
        "situations": [s.to_dict() for s in situations],
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    log(f"done in {report['wall_s']} s -> {out_dir}")
    return report


def _target_from(t: np.ndarray, club: int) -> dict:
    return {"aim": float(t[0]), "stroke_power": float(t[1]), "club_reach": float(t[2]), "club": BAG[int(club)].id}


def refit(src_dir: Path, out_dir: Path, log: Callable[[str], None] = print, feature_space: str | None = None) -> dict:
    """`fly-golf refit`: redo steps 4-6 from a finished run's SAVED practice (features.npz +
    report.json): the same situations, neural features, targets and fixed channels, no brain
    simulation. For improving the fitting / calibration code without re-simulating the connectome;
    the new report records the run it was refitted from. `feature_space` (default: the source
    run's) can switch to the DN-type x side rates when the run saved them."""
    src = Path(src_dir)
    rep = json.loads((src / "report.json").read_text())
    z = np.load(src / "features.npz")
    if "fixed" not in z:
        raise ValueError(f"{src} predates saved fixed channels; re-run `fly-golf train` instead")
    from ..brain.trained import load_readout

    feature_space = feature_space or rep["meta"].get("feature_space", FEATURE_SPACE)
    if "feature_names" in z:
        names = {FEATURE_SPACE: [str(n) for n in z["feature_names"]]}
    else:  # runs before feature spaces existed were all fitted on DN types
        names = {FEATURE_SPACE: list(load_readout(src / "readout.json").feature_names)}
    if "features_side" in z:
        names[FEATURE_SPACE_SIDE] = [str(n) for n in z["feature_names_side"]]
    elif feature_space == FEATURE_SPACE_SIDE:
        raise ValueError(f"{src} saved no DN-type x side features; re-run `fly-golf train` instead")
    sensory_names = list(load_readout(src / "no_brain_readout.json").feature_names)
    fixed_names = [str(c) for c in z["fixed_channels"]]
    situations = [Situation.from_dict(d) for d in rep["situations"]]
    rows = [
        {
            "index": i,
            "features": z["features"][i].tolist(),
            **({"features_side": z["features_side"][i].tolist()} if "features_side" in z else {}),
            "fixed": dict(zip(fixed_names, map(float, z["fixed"][i]), strict=True)),
            "sensory": dict(zip(sensory_names, map(float, z["sensory"][i]), strict=True)),
            "target": _target_from(z["targets"][i], z["target_club"][i]),
            "target_no_brain": _target_from(z["targets_no_brain"][i], z["target_club_no_brain"][i]),
            "distance_to_pin_m": float(z["distance_to_pin_m"][i]),
        }
        for i in range(len(situations))
    ]
    m = rep["meta"]
    log(f"refitting {m['training_id']} ({len(situations)} situations) from saved practice...")
    counts = {k: m["situations"][k] for k in ("putt", "green", "short", "full", "seed") if k in m["situations"]}
    return fit_and_report(
        situations,
        rows,
        names,
        out_dir,
        int(m["situations"]["seed"]),
        m["graph"],
        counts,
        log=log,
        extra_meta={"refit_from": {"training_id": m["training_id"], "git": m["git"], "path": str(src)}},
        upper_bound=rep["evaluation"]["variants"].get("practice_best_upper_bound"),
        feature_space=feature_space,
    )


def default_jobs() -> int:
    return max(1, min(6, (os.cpu_count() or 2) - 2))
