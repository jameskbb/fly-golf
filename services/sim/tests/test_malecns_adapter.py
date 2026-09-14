"""MaleCNS adapter tests on the SYNTHETIC fixture graph (CI-safe), plus
integration tests on the real compiled graph (skipped when absent)."""

import pytest

from fly_golf.brain.interfaces import (
    LEGACY_MOTOR_CHANNELS,
    LEGACY_SENSORY_CHANNELS,
    MOTOR_CHANNELS,
    SENSORY_CHANNELS,
    BrainController,
    SensoryFrame,
)
from fly_golf.brain.malecns.controller import MaleCNSController
from fly_golf.brain.malecns.graph import load_compiled
from fly_golf.brain.malecns.populations import sensory_drive, sensory_drive_v2
from fly_golf.config import load_settings
from fly_golf.data.prepare import compiled_status
from fly_golf.experiments.runner import PuttingSession, replay_controller


def frame(**overrides) -> SensoryFrame:
    ch = dict.fromkeys(SENSORY_CHANNELS, 0.0)
    ch.update({"target_distance": 0.3, "green_speed": 0.5, "ball_at_rest": 1.0})
    ch.update(overrides)
    return SensoryFrame(channels=ch, encoder="test", version="0")


def run(ctrl, f):
    ctrl.reset(0)
    ctrl.observe(f)
    summary = ctrl.step(400.0)
    return summary, dict(ctrl.motor_output().channels)


def test_controller_protocol_and_labels(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    assert isinstance(c, BrainController)
    assert c.info.is_mock is False
    assert c.info.kind.value == "malecns"
    assert c.info.neuron_count == synthetic_graph.n


def test_sensory_drive_is_lateralized():
    left = sensory_drive(dict(frame(target_left=1.0).channels))
    right = sensory_drive(dict(frame(target_right=1.0).channels))
    assert left["LC10_L"] > left["LC10_R"]
    assert right["LC10_R"] > right["LC10_L"]


def test_motor_output_bounded_and_complete(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    summary, motor = run(c, frame(target_left=0.8))
    assert set(motor) == set(MOTOR_CHANNELS)
    assert all(0.0 <= v <= 1.0 for v in motor.values())
    assert summary.total_spikes > 0
    assert len(summary.bins) == 40


def test_lateralized_input_changes_aim_on_synthetic_wiring(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    _, left = run(c, frame(target_left=1.0))
    _, right = run(c, frame(target_right=1.0))
    assert left["aim_left"] > left["aim_right"]
    assert right["aim_right"] > right["aim_left"]


def test_deterministic_and_reset(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    a = run(c, frame(target_left=0.4))[1]
    b = run(c, frame(target_left=0.4))[1]
    assert a == b


def test_full_putt_through_session(synthetic_graph):
    s = PuttingSession(MaleCNSController(synthetic_graph))
    s.new_hole(5)
    rec = s.play_shot()
    assert rec["controller"]["kind"] == "malecns"
    assert rec["neural_summary"]["neuron_count"] == synthetic_graph.n
    assert replay_controller(rec, MaleCNSController(synthetic_graph))["identical"]


def test_step_requires_observe(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    c.reset(0)
    with pytest.raises(RuntimeError):
        c.step(400.0)


def legacy_frame(**overrides) -> SensoryFrame:
    ch = dict.fromkeys(LEGACY_SENSORY_CHANNELS, 0.0)
    ch.update({"target_distance": 0.3, "green_speed": 0.5, "ball_at_rest": 1.0})
    ch.update(overrides)
    return SensoryFrame(channels=ch, encoder="proxy-v0", version="proxy-sensory-v0.1")


def test_v01_frames_keep_the_v01_mapping(synthetic_graph):
    # Recorded v0.1 shots must replay: 9-channel input -> 7-channel output, and the v0.2-only
    # populations receive no drive at all.
    c = MaleCNSController(synthetic_graph)
    summary, motor = run(c, legacy_frame(target_left=0.6))
    assert set(motor) == set(LEGACY_MOTOR_CHANNELS)
    for pop in ("LC15", "leg_bristle", "R7d_R8d"):
        assert summary.populations[pop]["drive_mv"] == 0.0


def test_v02_drive_uses_new_populations():
    base = dict(frame().channels)
    far = sensory_drive_v2(base | {"target_far": 1.0, "water_on_line": 0.5, "lie_sand": 1.0})
    near = sensory_drive_v2(base | {"lie_green": 1.0})
    assert far["LC15"] > near["LC15"] == 0.0
    assert far["R7d_R8d"] > 0.0 and near["R7d_R8d"] == 0.0
    assert far["leg_bristle"] > near["leg_bristle"] > 0.0
    # the nine shared channels drive their populations exactly as in v0.1
    shared = sensory_drive(base)
    assert {k: near[k] for k in shared} == sensory_drive(base | {"lie_green": 1.0})


def test_features_are_per_dn_type(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    run(c, frame(target_left=1.0, target_far=0.8))
    f = c.last_features()
    assert f.shape == (len(c.feature_names),)
    assert set(c.feature_names) == {"DNa02", "DNg10", "DNp09"}
    assert (f >= 0).all() and f.sum() > 0


# ---------------------------------------------------------------- integration
REAL_READY = compiled_status(load_settings())["ready"]
skip_without_data = pytest.mark.skipif(not REAL_READY, reason="compiled MaleCNS graph not present (run `make data`)")


@pytest.fixture(scope="module")
def real_graph():
    return load_compiled(load_settings().compiled_dir)


@pytest.mark.integration
@skip_without_data
def test_real_counts_match_release(real_graph):
    assert real_graph.n == 166_700
    assert real_graph.edges == 25_582_938


@pytest.mark.integration
@skip_without_data
def test_real_populations_resolve(real_graph):
    sizes = MaleCNSController(real_graph).info.config["population_sizes"]
    # Exact sizes: docs/SENSORY_MAPPING.md and docs/MOTOR_MAPPING.md quote these numbers.
    assert sizes == {
        "LC10_L": 479,
        "LC10_R": 481,
        "JO-C_L": 46,
        "JO-C_R": 22,
        "JO-E_L": 157,
        "JO-E_R": 110,
        "steer_L": 2,
        "steer_R": 2,
        "DN_L": 656,
        "DN_R": 648,
        "DN_all": 1314,
        # v0.2 additions
        "LC15": 126,
        "leg_bristle": 688,
        "R7d_R8d": 158,
    }


@pytest.mark.integration
@skip_without_data
def test_real_input_changes_downstream_activity(real_graph):
    c = MaleCNSController(real_graph)
    quiet, _ = run(c, frame(target_distance=1.0, target_left=0.0, target_right=0.0))
    loud, _ = run(c, frame(target_distance=0.0, target_left=1.0))
    assert loud.total_spikes != quiet.total_spikes


@pytest.mark.integration
@skip_without_data
def test_real_all_edges_disconnected_silences_undriven_neurons(real_graph):
    import numpy as np

    c = MaleCNSController(real_graph)
    c.engine.weight = np.zeros_like(np.asarray(c.engine.weight))
    summary, motor = run(c, frame(target_distance=0.0, target_left=1.0))
    driven = sum(v["neurons"] for v in summary.populations.values() if v["role"] == "sensory")
    assert summary.active_neurons <= driven
    assert motor["strike"] == 0.0
