import numpy as np
import pytest

from fly_golf.brain.malecns.engine import DEFAULT_PARAMETERS, LIFEngine

DELAY_MS = DEFAULT_PARAMETERS.delay_ms


def chain(weights: dict[tuple[int, int], float], n: int) -> LIFEngine:
    edges = sorted(weights.items())
    pre = np.array([e[0][0] for e in edges], dtype=np.int64)
    post = np.array([e[0][1] for e in edges], dtype=np.int32)
    w = np.array([e[1] for e in edges], dtype=np.float32)
    ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(pre, minlength=n), out=ptr[1:])
    return LIFEngine(ptr, post, w)


def drive(n, idx, value=30.0):
    d = np.zeros(n, dtype=np.float32)
    d[idx] = value
    return d


def test_undriven_network_is_silent():
    e = chain({(0, 1): 50.0}, 2)
    total, _, _ = e.run(100.0)
    assert total.sum() == 0


def test_driven_neuron_fires_and_propagates():
    e = chain({(0, 1): 50.0}, 3)
    e.set_drive(drive(3, [0]))
    total, _, _ = e.run(100.0)
    assert total[0] > 5
    assert total[1] > 0
    assert total[2] == 0  # not connected


def test_synaptic_delay_is_respected():
    e = chain({(0, 1): 50.0}, 2)
    e.set_drive(drive(2, [0]))
    _, bins, _ = e.run(30.0, bin_ms=0.1)
    first_pre = int(np.flatnonzero(bins[:, 0])[0])
    first_post = int(np.flatnonzero(bins[:, 1])[0])
    assert (first_post - first_pre) * 0.1 >= DELAY_MS - 1e-9


def test_refractory_limits_rate():
    e = chain({}, 1)
    e.set_drive(drive(1, [0], 1000.0))
    total, _, _ = e.run(100.0)
    # The inter-spike interval can never be shorter than the 2.2 ms refractory period.
    assert total[0] <= int(100.0 / 2.2) + 1
    assert total[0] >= int(100.0 / 2.2) - 1  # and a saturating drive fires at that limit


def test_inhibition_reduces_firing():
    # Presynaptic cell fires fast (30 mV drive); target fires slowly (12 mV), so
    # inhibitory arrivals do not all coincide with the target's refractory period.
    d = drive(3, [0], 30.0)
    d[2] = 12.0
    excit = chain({(0, 2): 0.0}, 3)
    excit.set_drive(d)
    base, _, _ = excit.run(200.0)
    inhib = chain({(0, 2): -40.0}, 3)
    inhib.set_drive(d)
    with_inh, _, _ = inhib.run(200.0)
    assert base[2] > 0
    assert with_inh[2] < base[2]


def test_deterministic():
    def once():
        e = chain({(0, 1): 20.0, (1, 2): 20.0, (2, 0): -5.0}, 3)
        e.set_drive(drive(3, [0], 25.0))
        return e.run(200.0, bin_ms=10.0)[:2]

    a, b = once(), once()
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_reset_restores_state():
    e = chain({(0, 1): 50.0}, 2)
    e.set_drive(drive(2, [0]))
    first, _, _ = e.run(50.0)
    e.reset()
    e.set_drive(drive(2, [0]))
    again, _, _ = e.run(50.0)
    assert np.array_equal(first, again)


def test_all_edges_disconnected_silences_undriven_cells():
    e = chain({(0, 1): 0.0, (1, 2): 0.0}, 3)
    e.set_drive(drive(3, [0]))
    total, _, _ = e.run(100.0)
    assert total[0] > 0 and total[1] == 0 and total[2] == 0


def test_invalid_graph_rejected():
    with pytest.raises(ValueError):
        LIFEngine(np.array([0, 2], dtype=np.int64), np.array([0], dtype=np.int32), np.array([1.0], dtype=np.float32))
    e = chain({}, 2)
    with pytest.raises(ValueError):
        e.set_drive(np.array([np.nan, 0.0], dtype=np.float32))


# ------------------------------------------------------------------ analytic expectations
from fly_golf.brain.malecns.engine import LIFParameters  # noqa: E402

P = DEFAULT_PARAMETERS
REF_STEPS = 22
DELAY_STEPS = 18


def test_published_constants():
    assert (P.tau_m_ms, P.tau_g_ms, P.v_rest_mv, P.v_reset_mv, P.v_threshold_mv) == (20.0, 5.0, -52.0, -52.0, -45.0)
    assert (P.refractory_ms, P.delay_ms, P.dt_ms) == (2.2, 1.8, 0.1)
    assert P.steps(P.refractory_ms) == REF_STEPS and P.steps(P.delay_ms) == DELAY_STEPS


def test_propagator_matches_fine_numerical_integration():
    p_vv, p_vg, p_gg = P.propagator()
    u, g = 3.0, 7.0  # v - v_inf and g at the start of the step
    h = P.dt_ms / 200_000
    for _ in range(200_000):  # RK2 on du/dt = (-u + g)/tau_m, dg/dt = -g/tau_g
        du1, dg1 = (-u + g) / P.tau_m_ms, -g / P.tau_g_ms
        um, gm = u + 0.5 * h * du1, g + 0.5 * h * dg1
        u, g = u + h * (-um + gm) / P.tau_m_ms, g + h * (-gm / P.tau_g_ms)
    assert abs(u - (3.0 * p_vv + 7.0 * p_vg)) < 1e-10
    assert abs(g - 7.0 * p_gg) < 1e-10
    same = LIFParameters(tau_m_ms=10.0, tau_g_ms=10.0)
    assert same.propagator()[1] == pytest.approx(0.01 * np.exp(-0.01))


def _first_crossing(drive_mv: float) -> int:
    """Updates from rest until v > V_th under a constant drive (closed form, no engine)."""
    p_vv = P.propagator()[0]
    v_inf = P.v_rest_mv + drive_mv
    k = 1
    while v_inf + (P.v_rest_mv - v_inf) * p_vv**k <= P.v_threshold_mv:
        k += 1
    return k


@pytest.mark.parametrize("drive_mv", [7.5, 12.0, 20.0, 1000.0])
def test_spike_times_follow_the_closed_form(drive_mv):
    e = chain({}, 1)
    e.set_drive(drive(1, [0], drive_mv))
    _, bins, _ = e.run(300.0, bin_ms=0.1)
    steps = np.flatnonzero(bins[:, 0])
    k = _first_crossing(drive_mv)
    assert steps[0] == k - 1  # step s performs the (s+1)-th update
    # after a spike: 21 frozen steps, then k updates from reset (= rest) to threshold
    assert np.all(np.diff(steps) == REF_STEPS - 1 + k)


def test_subthreshold_drive_never_spikes_and_settles_at_rest_plus_drive():
    e = chain({}, 1)
    e.set_drive(drive(1, [0], 6.9))
    total, _, _ = e.run(500.0)
    assert total[0] == 0
    assert e.v[0] == pytest.approx(P.v_rest_mv + 6.9, abs=1e-6)


def test_arrival_step_and_first_effect_on_v():
    e = chain({(0, 1): 1.0}, 2)
    e.set_drive(drive(2, [0], 30.0))
    trace = []
    for _ in range(120):
        total, _, _ = e.run(0.1)
        trace.append((int(total[0]), float(e.g[1]), float(e.v[1])))
    spike_step = next(i for i, t in enumerate(trace) if t[0])
    assert all(t[1] == 0.0 for t in trace[: spike_step + DELAY_STEPS])
    assert trace[spike_step + DELAY_STEPS][1] == pytest.approx(1.0)  # g jumps by w at +18...
    assert trace[spike_step + DELAY_STEPS][2] == P.v_rest_mv  # ...v is still at rest...
    assert trace[spike_step + DELAY_STEPS + 1][2] > P.v_rest_mv  # ...and moves one step later


def test_refractory_neuron_ignores_input_and_stays_frozen():
    e = chain({(0, 1): 100.0, (2, 1): 50.0}, 3)
    d = np.zeros(3)
    d[0] = 30.0
    e.set_drive(d)
    for _ in range(200):
        total, _, _ = e.run(0.1)
        if total[1]:
            break
    spike = e.step_index - 1
    d[2] = 1000.0  # neuron 2 now fires at once; its spike reaches 1 inside 1's refractory period
    e.set_drive(d)
    for _ in range(REF_STEPS - 1):
        e.run(0.1)
        assert e.step_index - 1 - spike < REF_STEPS
        assert e.v[1] == P.v_reset_mv and e.g[1] == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dt_ms": 0.3},  # 2.2 ms is not a whole number of 0.3 ms steps
        {"delay_ms": 0.0},
        {"v_threshold_mv": -60.0},
        {"tau_m_ms": 0.0},
        {"refractory_ms": -1.0},
    ],
)
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        LIFParameters(**kwargs)


def test_binned_counts_sum_to_totals_with_a_partial_last_bin():
    e = chain({(0, 1): 30.0, (1, 2): 30.0}, 3)
    e.set_drive(drive(3, [0], 25.0))
    total, bins, _ = e.run(100.0, bin_ms=7.3)
    assert bins.shape == (14, 3)  # 1000 steps / 73 -> 13 full bins + 1 partial
    assert np.array_equal(bins.sum(axis=0), total)


def test_state_is_float64_and_has_no_hidden_randomness():
    e = chain({(0, 1): 20.0}, 2)
    assert e.v.dtype == np.float64 and e.g.dtype == np.float64
    e.set_drive(drive(2, [0], 25.0))
    a = e.run(50.0, bin_ms=1.0)[:2]
    e.reset()
    e.set_drive(drive(2, [0], 25.0))
    b = e.run(50.0, bin_ms=1.0)[:2]
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    assert e.step_index == 500 and e.total_spikes == int(b[0].sum())
