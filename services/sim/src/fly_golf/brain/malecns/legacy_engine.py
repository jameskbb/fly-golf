"""LEGACY engine `lif-doomfly-r2-adapted-v1`, kept for replay and older readouts only.

This was Fly Golf's neural engine until the Fly Golf-native `fly-golf-lif-v1` (`engine.py`)
replaced it. It is not used for new shots. It is kept unchanged so that:

* shot records made with it can still be re-simulated bit for bit (`fly-golf replay --controller`);
* readouts trained against it (every readout before `fly-golf-lif-v1`) run on the engine they were
  fitted to and are never silently paired with a different one;
* the parity suite (tests/test_lif_parity.py) can compare the two engines.

The `_advance` kernel is adapted from nftechie/doomfly `doom/engine.py`
(commit 71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33, MIT License,
Copyright (c) 2026 nftechie and DOOMFLY contributors), which follows the
membrane/synapse constants of the whole-brain LIF model of Shiu et al. (2024)
(MIT License, Copyright (c) 2023 Philip Shiu and Nico Spiller). See
THIRD_PARTY_NOTICES.md.

Model (all constants are modelling choices, not measured male-fly physiology):
    tau_m = 20 ms, tau_g = 5 ms, V_rest = V_reset = -52 mV, V_th = -45 mV,
    refractory = 2.2 ms, synaptic delay = 1.8 ms, dt = 0.1 ms,
    weight = synapse count x sign x 0.275 mV (set at compile time),
    external input = a constant "drive" (mV-equivalent) per neuron.
Analytic sub-threshold integration each step; spikes are delivered from a
ring buffer after the delay; neurons are only integrated once they have
received input or drive (the active set only grows), so cost scales with
activity rather than with the 166,700 x 25.6M graph size.

Fly Golf changes vs. upstream: named constants (Numba freezes them at compile
time), per-bin spike counting API, explicit state reset, no retina/lamina/sugar coupling (sensory injection lives in
`populations.py`), and a pure-NumPy fallback-free build (Numba required).
"""

from __future__ import annotations

import math
import time

import numpy as np
from numba import njit

ENGINE_VERSION = "lif-doomfly-r2-adapted-v1"
DT_MS = 0.1
TAU_M_MS = 20.0
TAU_G_MS = 5.0
V_REST = -52.0
V_THRESHOLD = -45.0
REFRACTORY_MS = 2.2
DELAY_MS = 1.8


@njit(cache=True)
def _advance(
    ptr,
    post,
    weight,
    v,
    g,
    refractory,
    drive,
    queue,
    queue_count,
    cursor,
    steps,
    dt,
    counts,
    active,
    active_flag,
    nactive,
):
    av = math.exp(-dt / TAU_M_MS)
    ag = math.exp(-dt / TAU_G_MS)
    coupling = (av - ag) / (TAU_M_MS / TAU_G_MS - 1.0)  # = (av - ag) / 3 for the default constants
    delay_slots = queue.shape[0]
    delay = int(round(DELAY_MS / dt))
    rfc = int(round(REFRACTORY_MS / dt))
    for _step in range(steps):
        # Delivery occurs after integration/threshold and before reset, matching the
        # reference schedule. A spike at tick t arrives at t+18 for dt=.1.
        slot = cursor % delay_slots
        for k in range(nactive[0]):
            i = active[k]
            if refractory[i] > 0:
                refractory[i] -= 1
            if refractory[i] == 0:
                v[i] = V_REST + (v[i] - V_REST) * av + drive[i] * (1.0 - av) + g[i] * coupling
                g[i] *= ag
                if v[i] > V_THRESHOLD:
                    counts[i] += 1
                    future = (cursor + delay) % delay_slots
                    queue[future, queue_count[future]] = i
                    queue_count[future] += 1
        for q in range(queue_count[slot]):
            i = queue[slot, q]
            for e in range(ptr[i], ptr[i + 1]):
                j = post[e]
                # Brian2's (unless refractory) makes g read-only, including
                # synaptic writes. Do not save arrivals for a later release.
                if refractory[j] > 0:
                    continue
                g[j] += weight[e]
                if active_flag[j] == 0:
                    active_flag[j] = 1
                    active[nactive[0]] = j
                    nactive[0] += 1
        queue_count[slot] = 0
        future = (cursor + delay) % delay_slots
        for q in range(queue_count[future]):
            i = queue[future, q]
            v[i] = V_REST
            g[i] = 0.0
            refractory[i] = rfc
        cursor += 1
    return cursor


class LIFEngine:
    """Owns neural state for one graph. Deterministic: no random numbers anywhere."""

    def __init__(self, ptr: np.ndarray, post: np.ndarray, weight: np.ndarray):
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
        self.dt = DT_MS
        self.delay_slots = int(round(DELAY_MS / DT_MS)) + 1
        self.queue = np.zeros((self.delay_slots, n), dtype=np.int32)
        self.reset()

    @property
    def edge_count(self) -> int:
        return len(self.post)

    def reset(self) -> None:
        n = self.n
        self.v = np.full(n, V_REST, dtype=np.float32)
        self.g = np.zeros(n, dtype=np.float32)
        self.refractory = np.zeros(n, dtype=np.int16)
        self.drive = np.zeros(n, dtype=np.float32)
        self.queue_count = np.zeros(self.delay_slots, dtype=np.int32)
        self.active = np.zeros(n, dtype=np.int32)
        self.active_flag = np.zeros(n, dtype=np.uint8)
        self.nactive = np.zeros(1, dtype=np.int32)
        self.cursor = 0
        self.sim_ms = 0.0
        self.total_spikes = 0

    def set_drive(self, drive: np.ndarray) -> None:
        drive = np.asarray(drive, dtype=np.float32)
        if drive.shape != (self.n,) or not np.isfinite(drive).all():
            raise ValueError("drive must be a finite vector with one entry per neuron")
        self.drive[:] = drive
        for i in np.flatnonzero(drive):
            if self.active_flag[i] == 0:
                self.active_flag[i] = 1
                self.active[self.nactive[0]] = i
                self.nactive[0] += 1

    def run(self, duration_ms: float, bin_ms: float | None = None) -> tuple[np.ndarray, np.ndarray, float]:
        """Advance `duration_ms`. Returns (per-neuron spike counts, per-bin counts [bins x n] or empty, wall s)."""
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        steps = int(round(duration_ms / self.dt))
        bin_steps = steps if bin_ms is None else max(1, int(round(bin_ms / self.dt)))
        total = np.zeros(self.n, dtype=np.int32)
        bins = []
        start = time.perf_counter()
        done = 0
        while done < steps:
            k = min(bin_steps, steps - done)
            counts = np.zeros(self.n, dtype=np.int32)
            self.cursor = _advance(
                self.ptr,
                self.post,
                self.weight,
                self.v,
                self.g,
                self.refractory,
                self.drive,
                self.queue,
                self.queue_count,
                self.cursor,
                k,
                self.dt,
                counts,
                self.active,
                self.active_flag,
                self.nactive,
            )
            total += counts
            if bin_ms is not None:
                bins.append(counts)
            done += k
        wall = time.perf_counter() - start
        self.sim_ms += steps * self.dt
        self.total_spikes += int(total.sum())
        binned = np.stack(bins) if bins else np.zeros((0, self.n), dtype=np.int32)
        return total, binned, wall
