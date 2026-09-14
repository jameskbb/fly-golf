"""Small deterministic networks for the LIF parity suite (tests/test_lif_parity.py).

Each scenario is a tiny invented network (it says nothing about the real fly), a list of phases
(constant drive per neuron in mV, held for a duration), and what to record. The same definitions
drive three simulators: Fly Golf's engine, the legacy engine and the Brian2 reference
(scripts/generate_lif_reference.py), whose results are frozen in tests/fixtures/lif_reference.json.
"""

from __future__ import annotations

import json

import numpy as np

DT_MS = 0.1


def _random_network(n: int, p: float, seed: int) -> tuple[list, list]:
    rng = np.random.default_rng(seed)
    edges = []
    for i in range(n):
        for j in range(n):
            if i != j and rng.random() < p:
                sign = 1.0 if rng.random() < 0.7 else -1.0
                edges.append((i, j, round(float(sign * rng.integers(1, 40) * 0.275), 6)))
    drive = {i: round(float(rng.uniform(8.0, 20.0)), 3) for i in range(0, n, 3)}
    return edges, drive


_rand_edges, _rand_drive = _random_network(40, 0.12, seed=7)

SCENARIOS: dict[str, dict] = {
    "isolated_neuron": {
        "about": "one neuron, no input: stays exactly at rest",
        "n": 1,
        "edges": [],
        "phases": [({}, 50.0)],
    },
    "driven_neuron": {
        "about": "constant drive above threshold: regular firing",
        "n": 1,
        "edges": [],
        "phases": [({0: 20.0}, 200.0)],
    },
    "excitatory_pair": {
        "about": "sub-threshold excitatory synapse: the target fires only by summation",
        "n": 2,
        "edges": [(0, 1, 2.75)],
        "phases": [({0: 30.0}, 150.0)],
    },
    "inhibitory_pair": {
        "about": "an inhibitory synapse slows a driven target",
        "n": 2,
        "edges": [(0, 1, -5.5)],
        "phases": [({0: 25.0, 1: 12.0}, 200.0)],
    },
    "feed_forward_chain": {
        "about": "five-neuron chain of strong excitatory synapses",
        "n": 5,
        "edges": [(0, 1, 60.0), (1, 2, 60.0), (2, 3, 60.0), (3, 4, 60.0)],
        "phases": [({0: 25.0}, 100.0)],
    },
    "recurrent_excitatory_loop": {
        "about": "three-neuron excitatory ring, kicked then left alone: activity keeps circulating",
        "n": 3,
        "edges": [(0, 1, 60.0), (1, 2, 60.0), (2, 0, 60.0)],
        "phases": [({0: 15.0}, 20.0), ({}, 100.0)],
    },
    "recurrent_inhibitory_loop": {
        "about": "two driven neurons inhibiting each other",
        "n": 2,
        "edges": [(0, 1, -8.25), (1, 0, -8.25)],
        "phases": [({0: 20.0, 1: 18.0}, 200.0)],
    },
    "refractory_saturation": {
        "about": "very strong drive: one spike every refractory period + one step",
        "n": 1,
        "edges": [],
        "phases": [({0: 1000.0}, 50.0)],
    },
    "arrival_during_refractory": {
        "about": "a strong input reaches the target while it is refractory and must be ignored",
        "n": 3,
        "edges": [(0, 2, 100.0), (1, 2, 100.0)],
        # neuron 1 fires once, 1.0 ms after neuron 0; its arrival falls in 2's refractory period
        "phases": [({0: 30.0, 1: 27.9}, 6.5), ({}, 20.0)],
    },
    "delayed_delivery": {
        "about": "a single spike and the exact step it arrives at",
        "n": 2,
        "edges": [(0, 1, 100.0)],
        "phases": [({0: 30.0}, 6.0), ({}, 20.0)],
    },
    "mixed_signs": {
        "about": "two excitatory and one inhibitory source converge on one target",
        "n": 4,
        "edges": [(0, 3, 8.25), (1, 3, 8.25), (2, 3, -11.0)],
        "phases": [({0: 22.0, 1: 16.0, 2: 19.0}, 200.0)],
    },
    "self_edge": {
        "about": "an excitatory autapse: with delay < refractory it always arrives while refractory",
        "n": 2,
        "edges": [(0, 0, 50.0), (0, 1, 3.0)],
        "phases": [({0: 12.0}, 150.0)],
    },
    "simultaneous_spikes": {
        "about": "four identical sources spike on the same step onto one target",
        "n": 5,
        "edges": [(0, 4, 2.2), (1, 4, 2.2), (2, 4, 2.2), (3, 4, 2.2)],
        "phases": [({0: 18.0, 1: 18.0, 2: 18.0, 3: 18.0}, 150.0)],
    },
    "long_quiet_period": {
        "about": "activity, then 500 ms without drive: everything decays back to rest",
        "n": 3,
        "edges": [(0, 1, 5.0), (1, 2, 5.0)],
        "phases": [({0: 30.0, 1: 5.0}, 30.0), ({}, 500.0)],
    },
    "drive_changes": {
        "about": "the drive switches between phases (as between decision windows)",
        "n": 4,
        "edges": [(0, 1, 27.5), (1, 2, -13.75), (2, 3, 27.5), (3, 0, 5.5)],
        "phases": [({0: 12.0, 3: 12.0}, 40.0), ({}, 10.0), ({0: 18.0, 2: 9.0}, 40.0)],
    },
    "random_network": {
        "about": "40 neurons, 12 % connectivity, 70 % excitatory, a third of them driven",
        "n": 40,
        "edges": _rand_edges,
        "phases": [(_rand_drive, 300.0)],
    },
}


def definition(scenario: dict) -> str:
    """Canonical text of a scenario, stored with its reference results to catch stale fixtures."""
    phases = [[{str(k): v for k, v in sorted(d.items())}, ms] for d, ms in scenario["phases"]]
    return json.dumps({"n": scenario["n"], "edges": [list(e) for e in scenario["edges"]], "phases": phases})


def csr(scenario: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """CSR arrays with rows sorted by (pre, post)."""
    n = scenario["n"]
    edges = sorted(scenario["edges"], key=lambda e: (e[0], e[1]))
    pre = np.array([e[0] for e in edges], dtype=np.int64)
    post = np.array([e[1] for e in edges], dtype=np.int32)
    weight = np.array([e[2] for e in edges], dtype=np.float32)
    ptr = np.zeros(n + 1, dtype=np.int64)
    if len(pre):
        np.cumsum(np.bincount(pre, minlength=n), out=ptr[1:])
    return ptr, post, weight


def drive_vector(n: int, drive: dict) -> np.ndarray:
    d = np.zeros(n, dtype=np.float64)
    for i, value in drive.items():
        d[int(i)] = value
    return d


def run_scenario(engine, scenario: dict) -> dict:
    """Run a scenario on an engine with the LIFEngine API; spikes as sorted [step, neuron] pairs
    and the state (v, g) at the end of every phase."""
    n = scenario["n"]
    step0 = 0
    events: list[list[int]] = []
    v_end, g_end = [], []
    for drive, ms in scenario["phases"]:
        engine.set_drive(drive_vector(n, drive))
        _, bins, _ = engine.run(ms, bin_ms=DT_MS)
        for k, i in zip(*np.nonzero(bins), strict=True):
            events.extend([[step0 + int(k), int(i)]] * int(bins[k, i]))
        step0 += bins.shape[0]
        v_end.append([float(x) for x in engine.v])
        g_end.append([float(x) for x in engine.g])
    events.sort()
    return {"spikes": events, "v_end": v_end, "g_end": g_end}
