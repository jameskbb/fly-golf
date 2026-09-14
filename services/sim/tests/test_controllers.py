import math

import pytest

from fly_golf.brain.interfaces import (
    LEGACY_MOTOR_CHANNELS as MOTOR_CHANNELS,
)
from fly_golf.brain.interfaces import (
    LEGACY_SENSORY_CHANNELS as SENSORY_CHANNELS,
)
from fly_golf.brain.interfaces import (
    BrainController,
    MotorCommand,
    SensoryFrame,
)
from fly_golf.brain.mock import MockBrainController
from fly_golf.brain.motor import HardwareMotorTarget, MotorDecoder
from fly_golf.brain.sensory import ProxySensoryEncoder
from fly_golf.golf.env import PuttingEnvironment
from fly_golf.golf.scenario import generate_scenario


def frame_for(seed: int) -> SensoryFrame:
    env = PuttingEnvironment(generate_scenario(seed))
    return ProxySensoryEncoder().encode(env.observe())


def run_mock(seed: int, ctrl_seed: int) -> dict:
    m = MockBrainController()
    m.reset(ctrl_seed)
    m.observe(frame_for(seed))
    assert m.step(400.0) is None  # the mock reports no neural statistics
    return dict(m.motor_output().channels)


def test_mock_is_a_brain_controller_and_labeled():
    m = MockBrainController()
    assert isinstance(m, BrainController)
    assert m.info.is_mock is True
    assert m.info.label == "MOCK CONTROLLER"
    assert m.info.neuron_count is None


def test_mock_is_deterministic():
    assert run_mock(5, 5000) == run_mock(5, 5000)
    assert run_mock(5, 5000) != run_mock(5, 5001)


@pytest.mark.parametrize("seed", range(20))
def test_motor_outputs_bounded(seed):
    out = run_mock(seed, seed)
    assert set(out) == set(MOTOR_CHANNELS)
    assert all(0.0 <= v <= 1.0 for v in out.values())


def test_reset_restores_initial_state():
    m = MockBrainController()
    m.reset(3)
    m.observe(frame_for(1))
    m.step(400)
    first = dict(m.motor_output().channels)
    m.step(400)  # advance rng
    m.reset(3)
    m.observe(frame_for(1))
    m.step(400)
    assert dict(m.motor_output().channels) == first


def test_motor_output_before_step_raises():
    m = MockBrainController()
    with pytest.raises(RuntimeError):
        m.motor_output()


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {k: 0.5 for k in SENSORY_CHANNELS} | {"target_left": float("nan")},
        {k: 0.5 for k in SENSORY_CHANNELS} | {"target_left": 1.5},
        {k: 0.5 for k in SENSORY_CHANNELS} | {"target_left": "0.5"},
        {k: 0.5 for k in SENSORY_CHANNELS} | {"perfect_aim_angle": 0.3},
        {k: 0.5 for k in SENSORY_CHANNELS[:-1]},
    ],
)
def test_malformed_sensory_input_rejected(bad):
    with pytest.raises(ValueError):
        SensoryFrame(channels=bad, encoder="test", version="0")


def test_malformed_motor_command_rejected():
    with pytest.raises(ValueError):
        MotorCommand(channels={k: 2.0 for k in MOTOR_CHANNELS}, source="x")


def test_encoder_channels_bounded_and_complete():
    for seed in range(30):
        f = frame_for(seed)
        assert tuple(f.channels) == SENSORY_CHANNELS
        assert all(0.0 <= v <= 1.0 for v in f.channels.values())


def test_encoder_rejects_non_observation():
    with pytest.raises(ValueError):
        ProxySensoryEncoder().encode({"distance_m": 3})


def test_encoder_does_not_leak_solution():
    # Only perceptual channels: no aim angle, no power, no cup coordinates.
    f = frame_for(0)
    assert not any(k in f.channels for k in ("aim", "power", "cup_x", "perfect_aim_angle"))


def test_decoder_neutral_command_strikes_along_body_heading():
    cmd = MotorCommand(
        channels={
            "aim_left": 0,
            "aim_right": 0,
            "stroke_power": 0.5,
            "stroke_tempo": 0.5,
            "face_open": 0,
            "face_closed": 0,
            "strike": 1,
        },
        source="t",
    )
    d = MotorDecoder().decode(cmd, 1.0)
    assert d.stroke.heading_rad == pytest.approx(1.0)
    assert d.stroke.speed_mps == pytest.approx(0.5 * 4.2)
    assert d.contact


def test_decoder_aim_left_rotates_counterclockwise_and_no_strike_whiffs():
    base = {
        "aim_left": 1,
        "aim_right": 0,
        "stroke_power": 0.5,
        "stroke_tempo": 0.5,
        "face_open": 0,
        "face_closed": 0,
        "strike": 0.2,
    }
    d = MotorDecoder().decode(MotorCommand(channels=base, source="t"), 0.0)
    assert d.stroke.heading_rad == pytest.approx(math.radians(25))
    assert not d.contact and d.stroke.speed_mps == 0.0


def test_hardware_target_is_reserved():
    with pytest.raises(NotImplementedError):
        HardwareMotorTarget().execute(None)
