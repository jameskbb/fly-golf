"""Fly Golf's leaky integrate-and-fire engine, `fly-golf-lif-v1`.

Written for Fly Golf from the published model specification (docs/LIF_ENGINE.md), not from any
other implementation's source. The model is the whole-brain LIF model of Shiu et al. (2024,
*Nature* 634:210), whose reference implementation (`model.py`, Brian2, MIT) defines:

    dv/dt = (V_rest - v + g + I) / tau_m        (unless refractory)
    dg/dt = -g / tau_g                           (unless refractory)
    spike when v > V_th;  then v <- V_reset, g <- 0, refractory for t_ref
    a presynaptic spike adds w to the target's g after the delay t_dly

with tau_m = 20 ms, tau_g = 5 ms, V_rest = V_reset = -52 mV, V_th = -45 mV, t_ref = 2.2 ms,
t_dly = 1.8 ms, and w = synapse count x sign x 0.275 mV (fixed when the graph is compiled).
`I` is Fly Golf's sensory drive: a constant per neuron for a whole decision window (mV), where
the reference model uses Poisson input. dt = 0.1 ms, as in the reference.

Semantics (each checked against Brian2 in tests/test_lif_parity.py):

* Integration is exact for the linear system over each dt (the propagator below), like Brian2's
  `linear` / `exact` method, so dt only sets when threshold crossings are noticed.
* "unless refractory": for t_ref after a spike, v and g are frozen, and synaptic arrivals are
  ignored (Brian2 does not let a synapse write a variable that is frozen by refractoriness).
* One time step, in Brian2's default order: (1) integrate every non-refractory neuron; (2) every
  neuron above threshold spikes; (3) spikes emitted `delay` steps ago are delivered; (4) this
  step's spikers are reset. A spike at step s therefore reaches g at step s + 18, and moves v
  from step s + 19.
* A neuron is refractory while (step - last spike step) < 22, so it integrates again 22 steps
  after its spike.

Fly Golf implementation choices (docs/LIF_ENGINE.md): state is float64 (as in Brian2); within a
step, neurons are integrated and spikes delivered in ascending neuron index, so the order of
floating-point additions never depends on history; a neuron exactly at rest with no input and no
drive is skipped, because the exact update would return the same state bit for bit. No random
numbers are used anywhere.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np
from numba import njit

ENGINE_VERSION = "fly-golf-lif-v1"
_NEVER = -(2**62)  # "last spike" of a neuron that has not spiked yet


@dataclass(frozen=True)
class LIFParameters:
    """Model constants. The defaults are the published values (Shiu et al. 2024)."""

    tau_m_ms: float = 20.0
    tau_g_ms: float = 5.0
    v_rest_mv: float = -52.0
    v_reset_mv: float = -52.0
    v_threshold_mv: float = -45.0
    refractory_ms: float = 2.2
    delay_ms: float = 1.8
    dt_ms: float = 0.1

    def __post_init__(self) -> None:
        values = asdict(self)
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError("LIF parameters must be finite")
        if min(self.tau_m_ms, self.tau_g_ms, self.dt_ms) <= 0:
            raise ValueError("time constants and dt must be positive")
        if self.v_rest_mv >= self.v_threshold_mv or self.v_reset_mv >= self.v_threshold_mv:
            raise ValueError("rest and reset potentials must lie below threshold")
        if self.refractory_ms < 0:
            raise ValueError("refractory period cannot be negative")
        if self.steps(self.delay_ms) < 1:
            raise ValueError("the synaptic delay must be at least one time step")
        self.steps(self.refractory_ms)

    def steps(self, ms: float) -> int:
        """A duration as a whole number of time steps (rejects durations that are not)."""
        k = round(ms / self.dt_ms)
        if abs(k * self.dt_ms - ms) > 1e-9 * max(1.0, abs(ms)):
            raise ValueError(f"{ms} ms is not a whole number of {self.dt_ms} ms steps")
        return int(k)

    def propagator(self) -> tuple[float, float, float]:
        """Exact one-step solution of the linear system, as (p_vv, p_vg, p_gg):

        (v - v_inf)' = (v - v_inf) * p_vv + g * p_vg,   g' = g * p_gg,   v_inf = V_rest + I.

        With g(t) = g0 exp(-t/tau_g), v - v_inf has the particular solution
        A exp(-t/tau_g), A = g0 tau_g / (tau_g - tau_m), which gives p_vg below.
        """
        dt, tm, tg = self.dt_ms, self.tau_m_ms, self.tau_g_ms
        p_vv = math.exp(-dt / tm)
        p_gg = math.exp(-dt / tg)
        p_vg = (dt / tm) * p_vv if tm == tg else tg / (tg - tm) * (p_gg - p_vv)  # tm == tg: the limit
        return p_vv, p_vg, p_gg


DEFAULT_PARAMETERS = LIFParameters()


@njit(cache=True)
def _simulate(
    ptr,
    post,
    weight,
    v,
    g,
    last_spike,
    drive,
    pending,
    pending_len,
    first_step,
    n_steps,
    bin_steps,
    binned,
    p_vv,
    p_vg,
    p_gg,
    v_rest,
    v_reset,
    v_threshold,
    refractory_steps,
    delay_steps,
):
    """Advance `n_steps` steps from global step `first_step`; spikes are counted into `binned`.

    `pending[slot]` lists the neurons that spiked at a step congruent to `slot` modulo
    delay_steps + 1; it is delivered delay_steps later, and cleared before the slot is reused.
    """
    n = v.shape[0]
    slots = pending.shape[0]
    for k in range(n_steps):
        step = first_step + k
        row = k // bin_steps
        now = step % slots
        pending_len[now] = 0  # spikes from step - slots were delivered one step ago

        # (1) integrate and (2) threshold, in ascending neuron order
        for i in range(n):
            if step - last_spike[i] < refractory_steps:
                continue
            vi = v[i]
            gi = g[i]
            drive_i = drive[i]
            if gi == 0.0 and drive_i == 0.0 and vi == v_rest:
                continue  # at the fixed point: the exact update would not change anything
            v_inf = v_rest + drive_i
            vi = v_inf + (vi - v_inf) * p_vv + gi * p_vg
            v[i] = vi
            g[i] = gi * p_gg
            if vi > v_threshold:
                last_spike[i] = step
                pending[now, pending_len[now]] = i
                pending_len[now] += 1
                binned[row, i] += 1

        # (3) deliver the spikes emitted delay_steps ago; refractory targets ignore them
        then = (step - delay_steps) % slots
        for q in range(pending_len[then]):
            src = pending[then, q]
            for e in range(ptr[src], ptr[src + 1]):
                j = post[e]
                if step - last_spike[j] >= refractory_steps:
                    g[j] += weight[e]

        # (4) reset this step's spikers
        for q in range(pending_len[now]):
            i = pending[now, q]
            v[i] = v_reset
            g[i] = 0.0


class LIFEngine:
    """Neural state for one CSR graph. Deterministic: the same inputs give the same spikes."""

    version = ENGINE_VERSION

    def __init__(
        self,
        ptr: np.ndarray,
        post: np.ndarray,
        weight: np.ndarray,
        params: LIFParameters = DEFAULT_PARAMETERS,
    ):
        n = len(ptr) - 1
        if n < 1 or ptr[0] != 0 or ptr[-1] != len(post) or len(weight) != len(post):
            raise ValueError("invalid CSR graph")
        if np.any(np.diff(ptr) < 0):
            raise ValueError("CSR ptr must be non-decreasing")
        if len(post) and (int(post.min()) < 0 or int(post.max()) >= n):
            raise ValueError("post index out of range")
        if not np.isfinite(weight).all():
            raise ValueError("non-finite synaptic weight")
        self.ptr = np.ascontiguousarray(ptr, dtype=np.int64)
        self.post = np.ascontiguousarray(post, dtype=np.int32)
        self.weight = np.ascontiguousarray(weight, dtype=np.float32)
        self.n = n
        self.params = params
        self.dt = params.dt_ms
        self._delay_steps = params.steps(params.delay_ms)
        self._refractory_steps = params.steps(params.refractory_ms)
        self._pending = np.zeros((self._delay_steps + 1, n), dtype=np.int32)
        self.reset()

    @property
    def edge_count(self) -> int:
        return len(self.post)

    def describe(self) -> dict:
        return {"version": ENGINE_VERSION, "state_dtype": "float64", **asdict(self.params)}

    def reset(self) -> None:
        """Every neuron at rest, no input in flight, no drive, clock at zero."""
        n = self.n
        self.v = np.full(n, self.params.v_rest_mv, dtype=np.float64)
        self.g = np.zeros(n, dtype=np.float64)
        self.last_spike = np.full(n, _NEVER, dtype=np.int64)
        self.drive = np.zeros(n, dtype=np.float64)
        self._pending_len = np.zeros(self._delay_steps + 1, dtype=np.int32)
        self.step_index = 0
        self.sim_ms = 0.0
        self.total_spikes = 0

    def set_drive(self, drive: np.ndarray) -> None:
        """Constant external input (mV) per neuron, held until the next call."""
        drive = np.asarray(drive, dtype=np.float64)
        if drive.shape != (self.n,) or not np.isfinite(drive).all():
            raise ValueError("drive must be a finite vector with one entry per neuron")
        self.drive[:] = drive

    def run(self, duration_ms: float, bin_ms: float | None = None) -> tuple[np.ndarray, np.ndarray, float]:
        """Advance `duration_ms`. Returns (spikes per neuron, spikes per bin [bins x n] or an empty
        [0 x n] array when `bin_ms` is None, wall seconds). A final partial bin is kept."""
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        steps = int(round(duration_ms / self.dt))
        if steps < 1:
            raise ValueError("duration_ms is shorter than one time step")
        bin_steps = steps if bin_ms is None else max(1, int(round(bin_ms / self.dt)))
        binned = np.zeros((-(-steps // bin_steps), self.n), dtype=np.int32)
        p = self.params
        p_vv, p_vg, p_gg = p.propagator()
        start = time.perf_counter()
        _simulate(
            self.ptr,
            self.post,
            self.weight,
            self.v,
            self.g,
            self.last_spike,
            self.drive,
            self._pending,
            self._pending_len,
            self.step_index,
            steps,
            bin_steps,
            binned,
            p_vv,
            p_vg,
            p_gg,
            p.v_rest_mv,
            p.v_reset_mv,
            p.v_threshold_mv,
            self._refractory_steps,
            self._delay_steps,
        )
        wall = time.perf_counter() - start
        total = binned.sum(axis=0, dtype=np.int32)
        self.step_index += steps
        self.sim_ms += steps * self.dt
        self.total_spikes += int(total.sum())
        if bin_ms is None:
            binned = np.zeros((0, self.n), dtype=np.int32)
        return total, binned, wall


def make_engine(version: str, ptr: np.ndarray, post: np.ndarray, weight: np.ndarray):
    """The engine a controller, readout or replayed record asks for, by version string."""
    if version == ENGINE_VERSION:
        return LIFEngine(ptr, post, weight)
    from .legacy_engine import ENGINE_VERSION as LEGACY_VERSION
    from .legacy_engine import LIFEngine as LegacyLIFEngine

    if version == LEGACY_VERSION:
        return LegacyLIFEngine(ptr, post, weight)
    raise ValueError(f"unknown neural engine {version!r}")
