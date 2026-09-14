"""LIF parity suite: Fly Golf's engine against the Brian2 reference, and the legacy engine frozen.

The reference results come from Brian2 running the Shiu et al. (2024) model equations
(scripts/generate_lif_reference.py) and are frozen in tests/fixtures/lif_reference.json, so CI
needs neither Brian2 nor the connectome. See docs/LIF_ENGINE.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fly_golf.brain.malecns.engine import LIFEngine  # noqa: E402
from fly_golf.brain.malecns.legacy_engine import ENGINE_VERSION as LEGACY_VERSION  # noqa: E402
from fly_golf.brain.malecns.legacy_engine import LIFEngine as LegacyLIFEngine  # noqa: E402
from lif_scenarios import DT_MS, SCENARIOS, csr, definition, run_scenario  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "lif_reference.json").read_text())
REFERENCE = FIXTURE["scenarios"]
# Where the legacy float32 kernel parts from the float64 reference (documented in LIF_ENGINE.md).
LEGACY_DIVERGES = {"random_network"}


def test_fixture_is_current():
    assert set(REFERENCE) == set(SCENARIOS), "regenerate: scripts/generate_lif_reference.py"
    for name, scenario in SCENARIOS.items():
        assert REFERENCE[name]["definition"] == definition(scenario), f"{name} changed; regenerate the fixture"
    assert FIXTURE["legacy_engine"] == LEGACY_VERSION
    assert FIXTURE["dt_ms"] == DT_MS


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_engine_matches_brian2_reference(name):
    got = run_scenario(LIFEngine(*csr(SCENARIOS[name])), SCENARIOS[name])
    ref = REFERENCE[name]["brian2"]
    assert got["spikes"] == ref["spikes"]
    np.testing.assert_allclose(got["v_end"], ref["v_end"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(got["g_end"], ref["g_end"], rtol=0, atol=1e-9)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_legacy_engine_is_frozen(name):
    """The legacy engine must keep reproducing its own recorded behaviour (old records replay)."""
    got = run_scenario(LegacyLIFEngine(*csr(SCENARIOS[name])), SCENARIOS[name])
    assert got == REFERENCE[name]["legacy"]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_legacy_versus_reference_is_documented(name):
    same = REFERENCE[name]["legacy"]["spikes"] == REFERENCE[name]["brian2"]["spikes"]
    assert same == (name not in LEGACY_DIVERGES)


def test_scenarios_exercise_what_they_claim():
    def per_neuron(name):
        spikes = REFERENCE[name]["brian2"]["spikes"]
        return np.bincount([s[1] for s in spikes], minlength=SCENARIOS[name]["n"])

    assert per_neuron("isolated_neuron").sum() == 0
    assert per_neuron("excitatory_pair")[1] == 0  # sub-threshold on its own...
    assert per_neuron("feed_forward_chain").min() > 0  # ...but strong synapses carry spikes down the chain
    assert per_neuron("recurrent_excitatory_loop").min() > 1  # the ring keeps going after the kick
    assert per_neuron("arrival_during_refractory")[2] == 1  # the second arrival is ignored
    assert per_neuron("self_edge")[1] == 0 and per_neuron("self_edge")[0] > 0
    assert per_neuron("mixed_signs")[3] == 0
    steps = [s[0] for s in REFERENCE["delayed_delivery"]["brian2"]["spikes"]]
    assert len(steps) == 2 and steps[1] - steps[0] > 18  # arrival at +18 steps, effect on v from +19
    quiet = REFERENCE["long_quiet_period"]["brian2"]
    np.testing.assert_allclose(quiet["v_end"][-1], -52.0, atol=1e-6)


def test_running_in_pieces_equals_one_run():
    s = SCENARIOS["random_network"]
    one = LIFEngine(*csr(s))
    one.set_drive(np.array([s["phases"][0][0].get(i, 0.0) for i in range(s["n"])]))
    total_one, bins_one, _ = one.run(300.0, bin_ms=10.0)
    pieces = LIFEngine(*csr(s))
    pieces.set_drive(one.drive.copy())
    parts = [pieces.run(ms, bin_ms=10.0) for ms in (100.0, 50.0, 150.0)]
    assert np.array_equal(total_one, sum(p[0] for p in parts))
    assert np.array_equal(bins_one, np.concatenate([p[1] for p in parts]))
    assert np.array_equal(one.v, pieces.v) and np.array_equal(one.g, pieces.g)


def test_edge_order_within_a_row_does_not_matter():
    s = SCENARIOS["random_network"]
    ptr, post, weight = csr(s)
    rev_post, rev_weight = post.copy(), weight.copy()
    for i in range(s["n"]):
        a, b = ptr[i], ptr[i + 1]
        rev_post[a:b] = post[a:b][::-1]
        rev_weight[a:b] = weight[a:b][::-1]
    assert run_scenario(LIFEngine(ptr, post, weight), s) == run_scenario(LIFEngine(ptr, rev_post, rev_weight), s)


def test_live_brian2_oracle_on_fresh_random_networks():
    pytest.importorskip("brian2")
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from generate_lif_reference import run_brian2

    from lif_scenarios import _random_network

    for seed in (11, 12):
        edges, drive = _random_network(30, 0.15, seed=seed)
        s = {"n": 30, "edges": edges, "phases": [(drive, 150.0), ({}, 30.0)]}
        got = run_scenario(LIFEngine(*csr(s)), s)
        assert got["spikes"] == run_brian2(s)["spikes"]


@pytest.mark.integration
def test_full_malecns_graph_matches_brian2():
    """One practice situation on the real graph: every neuron's spike count equals Brian2's."""
    b2 = pytest.importorskip("brian2")
    from fly_golf.brain.malecns.controller import MaleCNSController
    from fly_golf.brain.malecns.graph import load_compiled
    from fly_golf.brain.sensory import ProxySensoryEncoderV2
    from fly_golf.config import load_settings
    from fly_golf.data.prepare import compiled_status
    from fly_golf.training.situations import generate_situations

    if not compiled_status()["ready"]:
        pytest.skip("compiled MaleCNS graph not present (run `make data`)")
    g = load_compiled(load_settings().compiled_dir)
    ctrl = MaleCNSController(g)
    frame = ProxySensoryEncoderV2().encode(generate_situations(2, 2, 2, 99, n_short=2)[0].build().observe())
    ctrl.reset(0)
    ctrl.observe(frame)
    drive = ctrl.engine.drive.copy()
    ours, _, _ = ctrl.engine.run(100.0)

    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = 0.1 * b2.ms
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from generate_lif_reference import EQUATIONS

    ns = {"v_0": -52 * b2.mV, "t_mbr": 20 * b2.ms, "tau": 5 * b2.ms, "v_th": -45 * b2.mV, "v_rst": -52 * b2.mV}
    neurons = b2.NeuronGroup(
        g.n, EQUATIONS, method="linear", threshold="v > v_th", reset="v = v_rst; g = 0 * mV",
        refractory=2.2 * b2.ms, namespace=ns,
    )  # fmt: skip
    neurons.v = -52 * b2.mV
    neurons.drive = drive * b2.mV
    syn = b2.Synapses(neurons, neurons, "w : volt", on_pre="g_post += w", delay=1.8 * b2.ms)
    syn.connect(i=np.repeat(np.arange(g.n, dtype=np.int32), np.diff(np.asarray(g.ptr))), j=np.asarray(g.post))
    syn.w = np.asarray(g.weight, dtype=np.float64) * b2.mV
    mon = b2.SpikeMonitor(neurons)
    b2.Network(neurons, syn, mon).run(100 * b2.ms)
    ref = np.bincount(np.asarray(mon.i[:]), minlength=g.n)
    assert ours.sum() > 1000
    assert np.array_equal(ours, ref)
