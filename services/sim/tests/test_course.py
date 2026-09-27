"""The 18-hole course, club bag, full-course physics, course environment, v2 sensing/decoding, rounds."""

import hashlib
import json
import math

import pytest

from fly_golf.brain.interfaces import LEGACY_MOTOR_CHANNELS, MOTOR_CHANNELS, SENSORY_CHANNELS, MotorCommand
from fly_golf.brain.mock import MockBrainController
from fly_golf.brain.motor import MotorDecoder, MotorDecoderV2
from fly_golf.brain.sensory import ProxySensoryEncoderV2
from fly_golf.experiments.runner import (
    RoundSession,
    RunRecorder,
    course_version_compatible,
    load_run,
    replay_controller,
    replay_physics,
)
from fly_golf.golf.clubs import BAG, CLUB_BY_ID, PUTTER, club_from_reach, nominal_distances, reach_for
from fly_golf.golf.course import (
    BACK_NINE,
    BACK_PAR,
    COURSE,
    COURSE_NAME,
    COURSE_PAR,
    COURSE_VERSION,
    FRINGE_M,
    FRONT_NINE,
    FRONT_PAR,
    HOLE_BY_NUMBER,
    NINES,
    TEE_RADIUS_M,
    course_summary,
)
from fly_golf.golf.course_env import MAX_OVER_PAR, CourseEnvironment, apply_lie
from fly_golf.golf.flight import FlatTerrain, Launch, Outcome, Surface, simulate_shot

NORTH = math.pi / 2


def full(club_id: str, heading: float = NORTH, fraction: float = 1.0, side: float = 0.0) -> Launch:
    c = CLUB_BY_ID[club_id]
    return Launch(c.ball_speed_mps * fraction, heading, c.launch_deg, c.spin_rpm * fraction, side)


def channels(**kw) -> dict:
    base = dict.fromkeys(MOTOR_CHANNELS, 0.0) | {"stroke_power": 0.5, "stroke_tempo": 0.5, "strike": 1.0}
    return base | kw


# ------------------------------------------------------------------------------ layout
def test_front_nine_layout():
    assert [h.number for h in FRONT_NINE] == list(range(1, 10))
    assert FRONT_PAR == 36
    assert sum(1 for h in FRONT_NINE if h.water) >= 2
    for h in FRONT_NINE:
        assert h.surface(*h.tee) is Surface.TEE
        assert h.surface(*h.cup) is Surface.GREEN
        assert h.route[0] == h.tee and h.route[-1] == h.cup
        assert 100 < h.length_m < 550
        assert h.surface(h.tee[0] + 500.0, h.tee[1]) is Surface.OOB


# The front nine as it was before the back nine existed (front-nine-v2): sha256 of
# json.dumps([h.to_dict() for h in FRONT_NINE], sort_keys=True) with only these keys. Holes 1-9
# must never change: recorded rounds and the trained readout's practice depend on them.
FRONT_NINE_V2_KEYS = (
    "bunkers",
    "collar_m",
    "corridor_half_width_m",
    "cup",
    "description",
    "fairways",
    "fringe_m",
    "green",
    "green_apron_m",
    "has_water",
    "length_m",
    "name",
    "number",
    "par",
    "route",
    "tee",
    "tee_radius_m",
    "trees",
    "water",
)
FRONT_NINE_V2_SHA256 = "eaa374e29f82f3e67d986adcee2e791b792a5d1b6b16270a30abcfc48236bdea"


def test_front_nine_geometry_is_pinned():
    dicts = [{k: h.to_dict()[k] for k in FRONT_NINE_V2_KEYS} for h in FRONT_NINE]
    digest = hashlib.sha256(json.dumps(dicts, sort_keys=True).encode()).hexdigest()
    assert digest == FRONT_NINE_V2_SHA256


def test_eighteen_hole_layout():
    assert [h.number for h in COURSE] == list(range(1, 19))
    assert COURSE == FRONT_NINE + BACK_NINE and sorted(HOLE_BY_NUMBER) == list(range(1, 19))
    assert COURSE_PAR == 72 and FRONT_PAR == BACK_PAR == 36
    assert COURSE_NAME == "Fly Golf National" and COURSE_VERSION == "eighteen-v1"
    assert [(n["id"], n["name"], n["holes"], n["par"]) for n in NINES] == [
        ("front", "Front Nine", list(range(1, 10)), 36),
        ("back", "The Neuropil Nine", list(range(10, 19)), 36),
    ]
    assert sorted(h.par for h in BACK_NINE) == [3, 3, 4, 4, 4, 4, 4, 5, 5]
    back_yards = sum(h.length_m for h in BACK_NINE) / 0.9144
    assert sum(h.length_m for h in FRONT_NINE) / 0.9144 < back_yards < 3800
    summary = course_summary()
    assert summary["par"] == 72 and len(summary["holes"]) == 18 and summary["nines"] == [dict(n) for n in NINES]


def test_every_hole_says_which_nine_and_theme():
    for h in COURSE:
        front = h.number <= 9
        for d in (h.to_dict(), h.to_dict(geometry=False)):
            assert d["nine"] == ("front" if front else "back")
            assert d["theme"] == ("parkland" if front else "dusk")
        assert h.to_dict()["corridor_half_width_m"] == h.corridor_half_width_m
    assert {h.corridor_half_width_m for h in FRONT_NINE} == {42.0}
    widths = {h.corridor_half_width_m for h in BACK_NINE}
    assert min(widths) <= 30.0 and max(widths) >= 55.0


def test_back_nine_holes_are_playable():
    for h in BACK_NINE:
        assert h.surface(*h.tee) is Surface.TEE and h.surface(*h.cup) is Surface.GREEN
        assert h.route[0] == h.tee and h.route[-1] == h.cup
        assert 100 < h.length_m < 600
        for p in h.route[1:-1]:
            assert h.surface(*p) is Surface.FAIRWAY, (h.number, p)
        g = h.green
        assert 9.0 <= g.radius_m <= 17.0 and 9.5 <= g.stimp_ft <= 12.5
        assert abs(g.slope_x) <= 0.02 and abs(g.slope_y) <= 0.02


def test_route_points_are_playable_and_inside_the_corridor():
    for h in COURSE:
        for p in h.route:
            assert h.surface(*p) in (Surface.TEE, Surface.FAIRWAY, Surface.GREEN), (h.number, p)
        for (ax, ay), (bx, by) in zip(h.route, h.route[1:], strict=False):
            for k in range(41):
                t = k / 40
                assert h.in_corridor(ax + (bx - ax) * t, ay + (by - ay) * t)


def test_no_water_over_a_green_or_tee_and_no_tee_in_sand():
    for h in COURSE:
        g = h.green
        for k in range(72):
            a = 2 * math.pi * k / 72
            for r in [0.5 * i for i in range(int(2 * (g.radius_m + FRINGE_M)) + 1)]:
                x, y = g.center[0] + r * math.cos(a), g.center[1] + r * math.sin(a)
                assert not any(w.contains(x, y) for w in h.water), (h.number, "green", x, y)
            for r in [0.5 * i for i in range(int(2 * TEE_RADIUS_M) + 1)]:
                x, y = h.tee[0] + r * math.cos(a), h.tee[1] + r * math.sin(a)
                assert not any(w.contains(x, y) for w in h.water), (h.number, "tee", x, y)
                assert not any(b.contains(x, y) for b in h.bunkers), (h.number, "tee sand", x, y)


def test_surface_respects_each_holes_corridor():
    chute, wide = HOLE_BY_NUMBER[17], HOLE_BY_NUMBER[16]
    assert chute.corridor_half_width_m < 30.0 < 55.0 <= wide.corridor_half_width_m
    assert chute.surface(0.0, 150.0) is Surface.FAIRWAY
    assert chute.surface(chute.corridor_half_width_m - 1.0, 150.0) is Surface.ROUGH
    assert chute.surface(chute.corridor_half_width_m + 1.0, 150.0) is Surface.OOB
    assert HOLE_BY_NUMBER[1].surface(35.0, 150.0) is Surface.ROUGH  # 42 m on the front nine
    assert wide.surface(-50.0, 200.0) is not Surface.OOB
    assert wide.surface(-wide.corridor_half_width_m - 4.0, 200.0) is Surface.OOB
    for h in COURSE:
        pad = 2.0 * h.corridor_half_width_m
        trees = h.trees
        assert trees and all(not h.in_corridor(t[0], t[1]) for t in trees if math.hypot(t[0], t[1]) > 60.0)
        assert h.surface(h.tee[0] + pad + 400.0, h.tee[1]) is Surface.OOB


def test_island_green_is_ringed_by_water():
    h = HOLE_BY_NUMBER[15]
    gx, gy = h.green.center
    assert h.water_on_line(h.tee, h.cup) > 0.05
    for k in range(36):
        a = 2 * math.pi * k / 36
        assert h.surface(gx + (h.green.radius_m + 3.0) * math.cos(a), gy + (h.green.radius_m + 3.0) * math.sin(a)) in (
            Surface.FAIRWAY,
            Surface.ROUGH,
            Surface.SAND,
        )
    wet = sum(
        h.surface(gx + 27.0 * math.cos(2 * math.pi * k / 72), gy + 27.0 * math.sin(2 * math.pi * k / 72))
        is Surface.WATER
        for k in range(72)
    )
    assert wet >= 60  # a ring of water, with a causeway gap


def test_island_green_drops_are_sane():
    h = HOLE_BY_NUMBER[15]
    heading = math.atan2(h.cup[1] - h.tee[1], h.cup[0] - h.tee[0])
    ring_front = h.green.center[1] - 34.0
    # A tee shot that comes up short drops on the tee side of the ring.
    env = CourseEnvironment(h, 1)
    _, out = env.step(full("gw", heading=heading))
    assert out.outcome == "water" and env.strokes == 2
    assert env.ball[1] < ring_front and h.surface(*env.ball) not in (Surface.WATER, Surface.OOB)
    # A tee shot over the island into the back of the ring drops back on the island.
    env = CourseEnvironment(h, 1)
    _, out = env.step(full("7i", heading=heading))
    assert out.outcome == "water"
    assert math.dist(env.ball, h.green.center) < 20.0 and h.surface(*env.ball) not in (Surface.WATER, Surface.OOB)
    # A chip from the island over the back drops on the island too.
    env = CourseEnvironment(h, 1)
    env.place((h.green.center[0], h.green.center[1] + 10.0), 0.0)
    _, out = env.step(full("lw", heading=NORTH, fraction=0.45))
    assert out.outcome == "water"
    assert math.dist(env.ball, h.green.center) < 20.0 and h.surface(*env.ball) not in (Surface.WATER, Surface.OOB)
    # The drop rule itself, walked by hand from either side of the ring.
    env = CourseEnvironment(h, 0)
    for start, entry in (((0.0, 0.0), (0.0, 100.0)), ((0.0, 128.0), (0.0, 158.0)), ((0.0, 0.0), (0.0, 158.0))):
        drop = env._water_drop(start, entry)
        assert h.surface(*drop) not in (Surface.WATER, Surface.OOB)


def test_front_nine_v2_records_of_holes_1_to_9_are_compatible():
    assert course_version_compatible("eighteen-v1", 12)
    assert course_version_compatible("front-nine-v2", 9)
    assert not course_version_compatible("front-nine-v2", 10)
    assert not course_version_compatible("front-nine-v1", 3)


def test_targets_follow_the_routing():
    h = HOLE_BY_NUMBER[4]  # par 5: tee -> landing area -> layup -> pin
    assert h.target_for(h.tee) == h.route[1]
    assert h.target_for(h.route[1]) == h.route[2]
    assert h.target_for((h.cup[0], h.cup[1] - 50.0)) == h.cup
    assert HOLE_BY_NUMBER[3].water_on_line(HOLE_BY_NUMBER[3].tee, HOLE_BY_NUMBER[3].cup) > 0.3
    assert HOLE_BY_NUMBER[1].water_on_line(HOLE_BY_NUMBER[1].tee, HOLE_BY_NUMBER[1].cup) == 0.0


def test_routing_never_targets_a_wedge_layup_after_a_drive():
    # Review finding: after a 220 m drive on the par 5s the target used to be a point 30 m away.
    for number in (4, 8):
        h = HOLE_BY_NUMBER[number]
        for s in (200.0, 220.0, 245.0):
            ball = (h.route[0][0], s)
            tx, ty = h.target_for(ball)
            assert math.hypot(tx - ball[0], ty - ball[1]) >= 60.0


def test_green_rim_is_continuous_for_physics():
    # Review finding: the green used to step up to 0.2 m at its rim.
    for h in FRONT_NINE:
        g = h.green
        for k in range(24):
            a = 2 * math.pi * k / 24
            r_in, r_out = g.radius_m - 1e-6, g.radius_m + 1e-6
            inside = h.height(g.center[0] + r_in * math.cos(a), g.center[1] + r_in * math.sin(a))
            outside = h.height(g.center[0] + r_out * math.cos(a), g.center[1] + r_out * math.sin(a))
            assert abs(inside - outside) < 1e-4
        assert h.height(g.center[0] + g.radius_m + 6.0, g.center[1]) == 0.0


# -------------------------------------------------------------------------------- clubs
def test_bag_order_and_reach():
    assert len(BAG) == 14
    assert BAG[0] is PUTTER and BAG[-1].id == "driver"
    assert club_from_reach(0.0) is PUTTER and club_from_reach(1.0).id == "driver"
    for c in BAG:
        assert club_from_reach(reach_for(c)) is c
    with pytest.raises(ValueError):
        club_from_reach(1.2)


def test_nominal_distances_are_ordered_and_plausible():
    d = nominal_distances()
    carries = [d[c.id]["carry_m"] for c in BAG[1:]]
    assert carries == sorted(carries)
    assert 55 < d["lw"]["carry_m"] < 80
    assert 135 < d["7i"]["carry_m"] < 160
    assert 210 < d["driver"]["carry_m"] < 245


# ------------------------------------------------------------------------------ physics
def test_flight_is_deterministic():
    a = simulate_shot(FlatTerrain(), (0.0, 0.0), full("7i"))
    b = simulate_shot(FlatTerrain(), (0.0, 0.0), full("7i"))
    assert a.trajectory == b.trajectory and a.outcome is Outcome.STOPPED


def test_backspin_lifts_and_sidespin_curves_left():
    spin = simulate_shot(FlatTerrain(), (0.0, 0.0), full("7i"))
    c = CLUB_BY_ID["7i"]
    none = simulate_shot(FlatTerrain(), (0.0, 0.0), Launch(c.ball_speed_mps, NORTH, c.launch_deg, 0.0, 0.0))
    assert spin.apex_m > none.apex_m
    left = simulate_shot(FlatTerrain(), (0.0, 0.0), full("driver", side=800.0))
    right = simulate_shot(FlatTerrain(), (0.0, 0.0), full("driver", side=-800.0))
    assert left.final_position[0] < -5.0 < 5.0 < right.final_position[0]  # facing north, left is -x


def test_putter_strike_rolls_without_flying():
    r = simulate_shot(FlatTerrain(), (0.0, 0.0), Launch(2.0, NORTH, 0.0, 0.0, 0.0))
    assert r.apex_m == 0.0 and r.carry_m == 0.0 and r.final_position[1] > 1.0


def test_rough_and_sand_slow_the_roll():
    roll = Launch(3.0, NORTH, 0.0, 0.0, 0.0)
    fair = simulate_shot(FlatTerrain(Surface.FAIRWAY), (0.0, 0.0), roll).final_position[1]
    rough = simulate_shot(FlatTerrain(Surface.ROUGH), (0.0, 0.0), roll).final_position[1]
    sand = simulate_shot(FlatTerrain(Surface.SAND), (0.0, 0.0), roll).final_position[1]
    assert fair > rough > sand > 0.0


def test_ball_landing_in_the_pond_is_water():
    h = HOLE_BY_NUMBER[3]
    r = simulate_shot(h, h.tee, full("lw", heading=math.atan2(h.cup[1], h.cup[0])))
    assert r.outcome is Outcome.WATER and r.hazard_entry is not None


def test_leaving_the_corridor_is_out_of_bounds():
    h = HOLE_BY_NUMBER[1]
    assert simulate_shot(h, h.tee, full("driver", heading=0.0)).outcome is Outcome.OUT_OF_BOUNDS


def test_ball_landing_on_the_cup_drops():
    landing = simulate_shot(FlatTerrain(), (0.0, 0.0), full("pw")).events[0]
    terrain = FlatTerrain()
    terrain.cup = (landing["x"], landing["y"])
    r = simulate_shot(terrain, (0.0, 0.0), full("pw"))
    assert r.outcome is Outcome.HOLED and r.events[-1].get("dunk")


# --------------------------------------------------------------------------- environment
def test_water_costs_a_stroke_and_drops_short_of_the_hazard():
    h = HOLE_BY_NUMBER[3]
    env = CourseEnvironment(h, 1)
    res, out = env.step(full("lw", heading=math.atan2(h.cup[1], h.cup[0])))
    assert out.outcome == "water" and out.penalty_strokes == 1 and env.strokes == 2
    assert h.surface(*env.ball) not in (Surface.WATER, Surface.OOB)
    assert env.ball[1] < res.hazard_entry[1]


def test_out_of_bounds_is_stroke_and_distance():
    h = HOLE_BY_NUMBER[1]
    env = CourseEnvironment(h, 1)
    _, out = env.step(full("driver", heading=0.0))
    assert out.outcome == "out_of_bounds" and env.ball == h.tee and env.strokes == 2


def test_hole_is_picked_up_at_par_plus_five():
    env = CourseEnvironment(HOLE_BY_NUMBER[6], 3)
    while not env.done:
        env.step(Launch(0.0, NORTH, 0.0, 0.0, 0.0, contact=False))
    assert env.state.value == "picked_up" and env.strokes == 3 + MAX_OVER_PAR


def test_lie_penalises_lofted_strikes_only():
    assert apply_lie(full("7i"), Surface.SAND).speed_mps == pytest.approx(0.72 * CLUB_BY_ID["7i"].ball_speed_mps)
    putt = Launch(2.0, NORTH, 0.0, 0.0, 0.0)
    assert apply_lie(putt, Surface.SAND) is putt
    assert apply_lie(full("7i"), Surface.FAIRWAY) == full("7i")


def test_place_puts_the_fly_facing_its_target():
    h = HOLE_BY_NUMBER[2]
    env = CourseEnvironment(h, 0)
    obs = env.place((0.0, 150.0), 0.0)
    assert obs.lie == "fairway" and abs(obs.bearing_rel_rad) < 1e-9
    with pytest.raises(ValueError):
        env.place((500.0, 500.0), 0.0)


# ------------------------------------------------------------------------------ v2 I/O
def test_encoder_v2_channels_and_lie_flags():
    enc = ProxySensoryEncoderV2()
    tee = enc.encode(CourseEnvironment(HOLE_BY_NUMBER[3], 0).observe()).channels
    assert tuple(tee) == SENSORY_CHANNELS
    assert tee["water_on_line"] > 0.3 and tee["lie_green"] == tee["lie_rough"] == tee["lie_sand"] == 0.0
    env = CourseEnvironment(HOLE_BY_NUMBER[1], 0)
    env.place((HOLE_BY_NUMBER[1].cup[0] + 3.0, HOLE_BY_NUMBER[1].cup[1]), 0.0)
    green = enc.encode(env.observe()).channels
    assert green["lie_green"] == 1.0 and green["target_distance"] == pytest.approx(0.3)


def test_decoder_v2_putter_matches_v1_and_driver_launches():
    ch = channels(aim_left=0.2, face_closed=0.3, stroke_power=0.4)
    v1 = MotorDecoder().decode(MotorCommand(channels={k: ch[k] for k in LEGACY_MOTOR_CHANNELS}, source="t"), 0.3)
    v2 = MotorDecoderV2().decode(MotorCommand(channels=ch, source="t"), 0.3)
    assert v2.club is PUTTER
    assert v2.stroke == v1.stroke
    d = MotorDecoderV2().decode(MotorCommand(channels=ch | {"club_reach": 1.0}, source="t"), 0.3)
    assert d.club.id == "driver" and d.launch.launch_deg == CLUB_BY_ID["driver"].launch_deg
    assert d.launch.speed_mps == pytest.approx(69.0 * (0.3 + 0.7 * 0.4))
    assert d.launch.sidespin_rpm > 0  # closed face -> curves left


def test_decoder_v2_forced_club_and_v1_command_rejected():
    ch = channels(club_reach=1.0)
    assert MotorDecoderV2().decode(MotorCommand(channels=ch, source="t"), 0.0, forced_club=PUTTER).club is PUTTER
    with pytest.raises(ValueError):
        MotorDecoderV2().decode(MotorCommand(channels={k: ch[k] for k in LEGACY_MOTOR_CHANNELS}, source="t"), 0.0)


# ------------------------------------------------------------------------------- rounds
def play_round(seed: int, recorder=None) -> RoundSession:
    s = RoundSession(MockBrainController(), recorder=recorder)
    s.new_round(seed)
    while True:
        while not s.env.done:
            s.play_shot()
        if s.round_complete:
            return s
        s.next_hole()


def test_mock_round_uses_the_whole_bag_sensibly():
    s = play_round(7)
    assert s.round_complete and 54 <= s._totals()["strokes"] <= 140
    card = [s.scorecard[n] for n in sorted(s.scorecard)]
    assert [c["hole"] for c in card] == list(range(1, 19))
    assert all(c["strokes"] is not None and c["holed"] for c in card)
    assert s.state()["totals"]["holes_played"] == 18 and s.state()["totals"]["par_played"] == 72


def test_round_records_replay_exactly(tmp_path):
    rec = RunRecorder(tmp_path, metadata={"mode": "course"})
    s = RoundSession(MockBrainController(), recorder=rec)
    s.new_round(11, start_hole=3)
    for _ in range(3):
        if s.env.done:
            break
        s.play_shot()
    shots = load_run(tmp_path, rec.run_id)["shots"]
    assert shots and all(r["mode"] == "course" for r in shots)
    assert {r["stroke"]["club"]["id"] for r in shots} - {"putter"}  # at least one full club
    for r in shots:
        assert replay_physics(r)["identical"]
        assert replay_controller(r, MockBrainController())["identical"]


def test_replaying_a_hole_is_a_new_attempt_and_rounds_are_kept(tmp_path):
    rec = RunRecorder(tmp_path)
    s = RoundSession(MockBrainController(), recorder=rec)
    s.new_round(3, start_hole=6)
    first = s.env.seed
    while not s.env.done:
        s.play_shot()
    s.start_hole(6)
    assert s.env.seed != first and s.attempts[6] == 1
    while not s.env.done:
        r = s.play_shot()
    assert r["course"]["attempt"] == 1 and "h6a1" in r["shot_id"]
    s.new_round(4, start_hole=6)
    while not s.env.done:
        s.play_shot()
    meta = load_run(tmp_path, rec.run_id)["run"]
    assert [r["seed"] for r in meta["rounds"]] == [3, 4]


def test_stats_never_count_past_the_pickup_cap():
    s = RoundSession(MockBrainController())
    s.new_round(1, start_hole=3)
    s.env.strokes = s.env.max_strokes - 1  # one stroke left before the pick-up
    s.play_shot()
    assert s.env.done and s.scorecard[3]["strokes"] <= s.env.max_strokes
    assert s.stats["strokes"] == 1 + s.stats["penalties"] or s.stats["strokes"] == 1


def test_round_flow_start_next_and_new_round():
    s = RoundSession(MockBrainController())
    s.new_round(2, start_hole=9)
    with pytest.raises(RuntimeError):
        s.next_hole()
    while not s.env.done:
        s.play_shot()
    assert s.next_hole()["hole_number"] == 10  # the next unplayed hole: the back nine
    with pytest.raises(ValueError):
        s.start_hole(19)
    s.new_round(2, start_hole=18)
    while not s.env.done:
        s.play_shot()
    assert s.next_hole()["hole_number"] == 1  # wraps to the first unplayed hole


def test_eighteen_hole_round_then_a_new_round():
    s = play_round(8)
    assert len(s.state()["scorecard"]) == 18 and s.round_complete
    total = s._totals()["strokes"]
    nxt = s.next_hole()  # after the 18th: a new round, hole 1, seed + 1
    assert nxt["hole_number"] == 1 and nxt["round_seed"] == 9 and not nxt["round_complete"]
    assert len(nxt["scorecard"]) == 18 and s.rounds[-1]["strokes"] == total


def test_front_nine_of_an_eighteen_hole_round_is_unchanged():
    # hole_seed() is unchanged, so holes 1-9 of an 18-hole round are the situations they always were.
    s = RoundSession(MockBrainController())
    s.new_round(7)
    assert s.env.seed == 71
    s.start_hole(12)
    assert s.env.seed == 82


def test_eighteen_hole_round_records_replay_exactly(tmp_path):
    rec = RunRecorder(tmp_path, metadata={"mode": "course"})
    play_round(12, recorder=rec)
    data = load_run(tmp_path, rec.run_id)
    shots = data["shots"]
    assert {r["course"]["hole_number"] for r in shots} == set(range(1, 19))
    assert len(data["run"]["round"]["scorecard"]) == 18 and data["run"]["round"]["complete"]
    for r in shots:
        assert r["course"]["version"] == COURSE_VERSION and r["course"]["par"] == 72
        rp = replay_physics(r)
        assert rp["identical"] and rp["course_compatible"]
        assert replay_controller(r, MockBrainController())["identical"]


def test_front_nine_v2_record_replays_on_the_eighteen_hole_course(tmp_path):
    rec = RunRecorder(tmp_path, metadata={"mode": "course"})
    s = RoundSession(MockBrainController(), recorder=rec)
    s.new_round(5, start_hole=3)
    while not s.env.done:
        s.play_shot()
    for r in load_run(tmp_path, rec.run_id)["shots"]:
        r["course"]["version"] = "front-nine-v2"  # as recorded before the back nine existed
        rp = replay_physics(r)
        assert rp["identical"] and rp["course_compatible"] and rp["course_version_recorded"] == "front-nine-v2"


MOCK_SEEDS = (*range(7, 17), *range(100, 112))


def test_mock_finishes_every_hole_with_a_plausible_score():
    # Every hole must be finishable and fair: the mock (a heuristic that reads the golf state)
    # holes out everywhere and averages within 1.5 strokes of par on every hole.
    per_hole: dict[int, list[int]] = {n: [] for n in range(1, 19)}
    for seed in MOCK_SEEDS:
        s = play_round(seed)
        for n, c in s.scorecard.items():
            assert c["holed"], (seed, n)
            per_hole[n].append(c["strokes"])
    for n, strokes in per_hole.items():
        mean = sum(strokes) / len(strokes)
        assert mean <= HOLE_BY_NUMBER[n].par + 1.5, (n, mean)
