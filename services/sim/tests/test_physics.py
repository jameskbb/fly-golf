import math

import pytest

from fly_golf.golf.physics import (
    CUP_RADIUS_M,
    Green,
    Outcome,
    Stroke,
    capture_speed,
    rest_is_stable,
    simulate_roll,
)
from fly_golf.golf.scenario import generate_scenario

FLAT = Green(stimp_ft=10.0)


def test_ball_at_rest_remains_at_rest():
    roll = simulate_roll(FLAT, (2.0, 0.0), (0.0, 0.0), Stroke(0.0, 0.0))
    assert roll.outcome is Outcome.STOPPED
    assert roll.final_position == (2.0, 0.0)


def test_ball_at_rest_on_gentle_slope_stays_put():
    green = Green(stimp_ft=10.0, slope_x=0.02)
    assert rest_is_stable(green)
    roll = simulate_roll(green, (2.0, 0.0), (0.0, 0.0), Stroke(0.0, 0.0))
    assert roll.outcome is Outcome.STOPPED
    assert roll.final_position == (2.0, 0.0)


def test_friction_reduces_speed_monotonically_on_flat():
    roll = simulate_roll(FLAT, (0.0, -5.0), (100.0, 100.0), Stroke(1.5, 0.0))
    xs = [p[1] for p in roll.trajectory]
    steps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
    # Distance covered per sample shrinks (speed decreasing), and the ball stops.
    assert all(later <= earlier + 1e-12 for earlier, later in zip(steps, steps[1:], strict=False))
    assert roll.outcome is Outcome.STOPPED


def test_stimpmeter_calibration():
    # A ball launched at the stimp release speed on a flat green rolls `stimp` feet.
    green = Green(stimp_ft=10.0)
    roll = simulate_roll(green, (0.0, -5.0), (100.0, 100.0), Stroke(1.83, 0.0))
    assert roll.final_position[0] == pytest.approx(10 * 0.3048, rel=0.01)


def test_identical_input_gives_identical_trajectory():
    green = Green(stimp_ft=9.3, slope_x=0.011, slope_y=-0.007)
    a = simulate_roll(green, (3.0, 1.0), (0.0, 0.0), Stroke(1.9, math.pi + 0.3))
    b = simulate_roll(green, (3.0, 1.0), (0.0, 0.0), Stroke(1.9, math.pi + 0.3))
    assert a.trajectory == b.trajectory
    assert a.outcome == b.outcome


def test_seeded_scenario_is_reproducible():
    assert generate_scenario(42) == generate_scenario(42)
    assert generate_scenario(42) != generate_scenario(43)


def test_centred_slow_ball_is_holed():
    roll = simulate_roll(FLAT, (1.0, 0.0), (0.0, 0.0), Stroke(1.2, math.pi))
    assert roll.outcome is Outcome.HOLED


def test_fast_centred_ball_does_not_drop():
    roll = simulate_roll(FLAT, (0.5, 0.0), (0.0, 0.0), Stroke(3.5, math.pi))
    assert roll.outcome is not Outcome.HOLED
    assert roll.lip_outs >= 1


def test_capture_is_consistent():
    results = {simulate_roll(FLAT, (1.0, 0.0), (0.0, 0.0), Stroke(1.2, math.pi)).outcome for _ in range(5)}
    assert results == {Outcome.HOLED}
    assert capture_speed(0.0) > capture_speed(CUP_RADIUS_M * 0.5) > capture_speed(CUP_RADIUS_M) == 0.0


def test_ball_missing_the_cup_is_not_holed():
    # Aimed 10 cm wide of the cup: never within the capture radius.
    heading = math.atan2(0.10, -2.0)
    roll = simulate_roll(FLAT, (2.0, 0.0), (0.0, 0.0), Stroke(1.6, heading))
    assert roll.outcome is Outcome.STOPPED
    assert roll.closest_approach_m > CUP_RADIUS_M


def test_slope_bends_trajectory_downhill():
    # Ground rises toward +y, so the ball should drift toward -y while rolling in +x.
    green = Green(stimp_ft=10.0, slope_y=0.02)
    roll = simulate_roll(green, (0.0, 0.0), (50.0, 50.0), Stroke(1.8, 0.0))
    assert roll.final_position[1] < -0.05
    flat = simulate_roll(FLAT, (0.0, 0.0), (50.0, 50.0), Stroke(1.8, 0.0))
    assert flat.final_position[1] == pytest.approx(0.0, abs=1e-12)


def test_uphill_putt_is_shorter_than_downhill():
    up = simulate_roll(Green(stimp_ft=10.0, slope_x=0.02), (0.0, 0.0), (50, 50), Stroke(1.8, 0.0))
    down = simulate_roll(Green(stimp_ft=10.0, slope_x=-0.02), (0.0, 0.0), (50, 50), Stroke(1.8, 0.0))
    assert up.final_position[0] < down.final_position[0]


def test_ball_leaving_green_is_flagged():
    roll = simulate_roll(Green(stimp_ft=12.0, radius_m=3.0), (0.0, 0.0), (50, 50), Stroke(4.0, 0.0))
    assert roll.outcome is Outcome.OFF_GREEN


def test_no_contact_does_not_move_the_ball():
    roll = simulate_roll(FLAT, (2.0, 0.0), (0.0, 0.0), Stroke(2.0, math.pi, contact=False))
    assert roll.outcome is Outcome.NO_CONTACT
    assert roll.final_position == (2.0, 0.0)


@pytest.mark.parametrize("bad", [float("nan"), -1.0, 99.0])
def test_invalid_stroke_rejected(bad):
    with pytest.raises(ValueError):
        Stroke(bad, 0.0)


def test_invalid_green_rejected():
    with pytest.raises(ValueError):
        Green(stimp_ft=2.0)
    with pytest.raises(ValueError):
        Green(slope_x=float("nan"))


def test_holed_putt_records_no_lip_out():
    roll = simulate_roll(FLAT, (1.0, 0.0), (0.0, 0.0), Stroke(1.5, math.pi))
    assert roll.outcome is Outcome.HOLED
    assert roll.lip_outs == 0
    assert [e["type"] for e in roll.events] == ["holed"]


def test_centred_lip_out_loses_substantial_speed():
    # A centred pass that is too fast lips once and keeps ~70% of its speed.
    roll = simulate_roll(FLAT, (0.5, 0.0), (0.0, 0.0), Stroke(2.4, math.pi))
    assert roll.outcome is not Outcome.HOLED
    lips = [e for e in roll.events if e["type"] == "lip"]
    assert len(lips) == 1
    assert lips[0]["speed"] < 0.8 * roll.max_speed_over_cup_mps


def test_grazing_lip_out_loses_little_speed():
    heading = math.atan2(0.05, -1.0)  # passes ~5 cm from centre: just inside the rim
    roll = simulate_roll(FLAT, (1.0, 0.0), (0.0, 0.0), Stroke(2.2, heading))
    lips = [e for e in roll.events if e["type"] == "lip"]
    assert lips and lips[0]["offset"] > 0.8 * CUP_RADIUS_M
    assert lips[0]["speed"] > 0.9 * roll.max_speed_over_cup_mps
