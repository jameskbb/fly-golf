"""Readout training on the SYNTHETIC graph (CI-safe; says nothing about the real fly)."""

import json

import numpy as np
import pytest

from fly_golf.brain.trained import (
    GatedReadout,
    LinearReadout,
    TrainedReadoutController,
    load_readout,
    swing_club_index,
)
from fly_golf.experiments.bench import play_round, summarize_rounds
from fly_golf.experiments.runner import PuttingSession, RoundSession, replay_controller
from fly_golf.golf.clubs import BAG
from fly_golf.golf.course import HOLE_BY_NUMBER
from fly_golf.golf.flight import Surface
from fly_golf.training.pipeline import (
    NEUTRAL_FULL,
    choose_club,
    fit_gated_readout,
    play_once,
    practice,
    shuffled_graph,
    train,
)
from fly_golf.training.situations import SHORT_MAX_M, SHORT_MIN_M, generate_situations


def test_situations_are_deterministic_and_split():
    a = generate_situations(20, 20, 30, seed=3, n_short=20)
    assert a == generate_situations(20, 20, 30, seed=3, n_short=20)
    assert [s.kind for s in a].count("full") == 30 and [s.kind for s in a].count("short") == 20
    frac = sum(s.is_test for s in a) / len(a)
    assert 0.25 < frac < 0.35
    # The v1 part of the layout is unchanged by adding short-game situations.
    assert a[:70] == generate_situations(20, 20, 30, seed=3)
    # Review finding: tee shots used to be aliased entirely into the training split.
    for scale in (0.25, 1, 3):
        sits = generate_situations(int(120 * scale), int(120 * scale), int(200 * scale))
        tees = [s for s in sits if s.kind == "full" and s.ball == HOLE_BY_NUMBER[s.hole].tee]
        assert any(s.is_test for s in tees) and any(not s.is_test for s in tees)
    for s in a:
        s.build()  # every situation is a legal ball position
    for s in a[70:]:
        hole = HOLE_BY_NUMBER[s.hole]
        d = np.hypot(hole.cup[0] - s.ball[0], hole.cup[1] - s.ball[1])
        assert SHORT_MIN_M <= d <= SHORT_MAX_M and hole.surface(*s.ball) is not Surface.GREEN


def test_shuffled_graph_preserves_degrees_and_weights(synthetic_graph):
    g = synthetic_graph
    sg = shuffled_graph(g, 1)
    assert np.array_equal(sg.ptr, g.ptr) and np.array_equal(sg.weight, g.weight)
    assert np.array_equal(np.bincount(sg.post, minlength=g.n), np.bincount(g.post, minlength=g.n))
    assert not np.array_equal(sg.post, g.post)


def test_practice_finds_a_stroke_at_least_as_good_as_the_fixed_one():
    sit = generate_situations(2, 0, 0)[0]
    fixed = {
        "aim_left": 0.3,
        "aim_right": 0.0,
        "stroke_power": 0.9,
        "stroke_tempo": 0.5,
        "face_open": 0.2,
        "face_closed": 0.0,
        "strike": 1.0,
        "club_reach": 0.5,
    }
    best = practice(sit, fixed)
    assert best["result"]["score"] >= play_once(sit, fixed)["score"]
    assert best["target"]["club"] == "putter"


def test_choose_club_prefers_the_least_club_that_is_about_as_good():
    # (robust score, bag index): the driver is best by a hair, the 8-iron is within tolerance.
    per_club = [(-60.0, 1), (-11.0, 6), (-8.0, 13), (-30.0, 9)]
    assert choose_club(per_club, 100.0) == 6  # tolerance 4 m at 100 m: the 8-iron is within it
    assert choose_club(per_club, 10.0) == 13  # tolerance 2 m: only the driver qualifies


def test_short_game_practice_reaches_for_a_short_club():
    """From a chip or pitch, practice must not pick a long iron (the user-visible v1 failure)."""
    sits = [s for s in generate_situations(0, 0, 0, seed=0, n_short=18) if s.kind == "short"]
    order = {c.id: i for i, c in enumerate(BAG)}
    for s in sits[:6]:
        env = s.build()
        if env.on_putting_surface:
            continue
        club = practice(s, NEUTRAL_FULL, env)["target"]["club"]
        assert order[club] <= order["8i"], (s, club)


def test_swing_club_index_never_decodes_the_putter():
    assert list(swing_club_index(np.array([-3.0, 0.4, 0.6, 6.49, 20.0]))) == [1, 1, 1, 6, 13]


def test_gated_fit_recovers_a_club_rule_and_round_trips(tmp_path):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 6))
    # Putts when feature 3 is high (a "lie" signal); otherwise the club grows with feature 0.
    putt = x[:, 3] > 0.3
    clubs = np.where(putt, 0, np.clip(np.round(7 + 2.4 * x[:, 0]), 1, len(BAG) - 1)).astype(int)
    aim_power = np.column_stack([0.2 * x[:, 1], np.clip(0.5 + 0.2 * x[:, 2], 0, 1)])
    ro, fit = fit_gated_readout(x, aim_power, clubs, [f"f{i}" for i in range(6)], transform="none")
    pred = np.array([BAG.index(next(c for c in BAG if c.id == ro.predict(r)["club"])) for r in x])
    assert ((pred == 0) == putt).mean() > 0.97
    assert np.abs(pred - clubs)[~putt].mean() < 0.6
    assert fit["gate"]["cv_error"] < 0.05
    ro.save(tmp_path / "r.json")
    back = load_readout(tmp_path / "r.json")
    assert isinstance(back, GatedReadout)
    a, b = back.predict(x[3]), ro.predict(x[3])
    assert a["club"] == b["club"] and a["head"] == b["head"]
    assert a["aim"] == pytest.approx(b["aim"], abs=1e-6) and a["stroke_power"] == pytest.approx(
        b["stroke_power"], abs=1e-6
    )


def test_v1_readouts_still_load(tmp_path):
    names = ["a", "b"]
    v1 = LinearReadout(names, np.zeros(2), np.ones(2), np.zeros((3, 2)), np.array([0.1, 0.5, 0.3]))
    v1.save(tmp_path / "v1.json")
    back = load_readout(tmp_path / "v1.json")
    assert isinstance(back, LinearReadout) and back.predict(np.ones(2))["club_reach"] == 0.3
    bad = json.loads((tmp_path / "v1.json").read_text()) | {"format": "nope"}
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_readout(tmp_path / "bad.json")


@pytest.fixture
def trained(synthetic_graph, tmp_path):
    report = train(
        synthetic_graph, tmp_path / "out", n_putt=6, n_green=6, n_full=6, n_short=6, jobs=1, log=lambda m: None
    )
    return report, load_readout(tmp_path / "out" / "readout.json"), tmp_path / "out"


def test_training_pipeline_end_to_end(trained, synthetic_graph):
    report, readout, out = trained
    assert (out / "report.json").exists() and (out / "no_brain_readout.json").exists()
    v = report["evaluation"]["variants"]
    assert {"fixed_v0.2_readout", "trained_readout", "no_brain_sensory_readout", "mock_heuristic"} <= set(v)
    assert "short" in v["trained_readout"] and "club_within1_pct" in v["trained_readout"]["full"]
    assert isinstance(readout, GatedReadout)
    assert readout.meta["method"] == "hindsight-gated-v2"
    assert readout.meta["graph"]["release"].startswith("SYNTHETIC")
    pred = readout.predict(np.ones(len(readout.feature_names)))
    assert -1 <= pred["aim"] <= 1 and 0 <= pred["stroke_power"] <= 1 and 0 <= pred["club_reach"] <= 1
    assert pred["club"] in {c.id for c in BAG}
    cal = report["fit"]["brain"]["calibration"]
    assert cal["n_swing"] + cal["n_putt"] == readout.meta["situations"]["train"]  # training situations only
    for head in ("swing", "putter"):  # the identity is in the grid: the pooled score can only improve
        before, after = cal["practice_score_before"][head], cal["practice_score_after"][head]
        assert after["pooled"] >= before["pooled"] - 1e-9
        for kind in (k for k in before if k != "pooled"):  # and no kind of shot may get much worse
            assert after[kind] >= before[kind] - 2 * cal["max_kind_drop_m"] - 1e-9
    assert readout.club_stretch == cal["club_stretch"] and readout.club_shift == cal["club_shift"]
    assert {"trained_readout_uncalibrated", "no_brain_uncalibrated"} <= set(v)


def test_calibration_moves_the_club_choice_shorter():
    names = ["f0"]
    ro = GatedReadout(
        names, np.zeros(1), np.ones(1), np.zeros(1), -10.0, np.zeros(1), 9.0,
        {"putter": np.zeros((2, 1)), "swing": np.zeros((2, 1))},
        {"putter": np.array([0.0, 0.5]), "swing": np.array([0.0, 0.8])},
    )  # fmt: skip
    assert ro.predict(np.zeros(1))["club"] == "5i"  # index 9
    shifted = GatedReadout.from_json(ro.to_json() | {"calibration": {"club_center": 7.0, "club_shift": 2.0}})
    assert shifted.predict(np.zeros(1))["club"] == "7i"  # index 7
    scaled = GatedReadout.from_json(ro.to_json() | {"calibration": {"power_scale": {"swing": 0.5}}})
    assert scaled.predict(np.zeros(1))["stroke_power"] == pytest.approx(0.4)


def test_trained_controller_plays_and_replays(trained, synthetic_graph):
    _, readout, _ = trained
    c = TrainedReadoutController(synthetic_graph, readout)
    assert c.info.id == "malecns-trained" and c.info.is_mock is False and "TRAINED" in c.info.label
    s = PuttingSession(c)
    s.new_hole(4)
    rec = s.play_shot()
    assert replay_controller(rec, TrainedReadoutController(synthetic_graph, readout))["identical"]
    r = RoundSession(c)
    r.new_round(1, start_hole=6)
    assert r.play_shot()["controller"]["id"] == "malecns-trained"
    assert c.last_prediction and c.last_prediction["club"] in {x.id for x in BAG}


def test_refit_reproduces_the_run_from_saved_practice(trained, tmp_path):
    from fly_golf.training.pipeline import refit

    report, readout, out = trained
    r2 = refit(out, tmp_path / "refit", log=lambda m: None)
    assert r2["meta"]["refit_from"]["training_id"] == report["meta"]["training_id"]
    assert r2["meta"]["situations"] == report["meta"]["situations"]
    assert r2["fit"]["brain"]["calibration"]["scored_out_of_fold"] is True
    # The same saved practice and the same code give the same readout and the same held-out results.
    again = load_readout(tmp_path / "refit" / "readout.json")
    assert again.feature_names == readout.feature_names
    assert np.allclose(again.club_weights, readout.club_weights) and again.club_shift == readout.club_shift
    assert r2["evaluation"]["variants"] == report["evaluation"]["variants"]


def test_readout_refuses_a_different_feature_space(trained, synthetic_graph):
    _, readout, _ = trained
    readout.feature_names = [*readout.feature_names[:-1], "DNxx99"]
    with pytest.raises(ValueError):
        TrainedReadoutController(synthetic_graph, readout)


def test_side_feature_space_refits_plays_and_replays(trained, synthetic_graph, tmp_path):
    from fly_golf.brain.malecns.controller import FEATURE_SPACE, FEATURE_SPACE_SIDE, FEATURE_SPACES, MaleCNSController
    from fly_golf.training.pipeline import refit

    report, readout, out = trained
    ctrl = MaleCNSController(synthetic_graph)
    names_side = ctrl.feature_names_for(FEATURE_SPACE_SIDE)
    assert all("|" in n for n in names_side) and len(names_side) >= len(ctrl.feature_names_for(FEATURE_SPACE))
    assert readout.feature_space == FEATURE_SPACE and report["meta"]["feature_space"] == FEATURE_SPACE
    # The same saved practice, refitted on DN type x side rates (no brain simulation).
    r2 = refit(out, tmp_path / "side", log=lambda m: None, feature_space=FEATURE_SPACE_SIDE)
    side = load_readout(tmp_path / "side" / "readout.json")
    assert side.feature_space == FEATURE_SPACE_SIDE and r2["meta"]["feature_space"] == FEATURE_SPACE_SIDE
    assert side.feature_names == names_side
    c = TrainedReadoutController(synthetic_graph, side)
    assert c.info.config["readout"]["feature_space"] == FEATURE_SPACE_SIDE
    s = PuttingSession(c)
    s.new_hole(4)
    rec = s.play_shot()
    assert replay_controller(rec, TrainedReadoutController(synthetic_graph, side))["identical"]
    # A refit without a feature space keeps the source run's; an unknown one is refused.
    again = refit(tmp_path / "side", tmp_path / "again", log=lambda m: None)
    assert again["meta"]["feature_space"] == FEATURE_SPACE_SIDE
    side.feature_space = "nope"
    with pytest.raises(ValueError):
        TrainedReadoutController(synthetic_graph, side)
    assert FEATURE_SPACES == (FEATURE_SPACE, FEATURE_SPACE_SIDE)


def test_stratified_folds_and_pca_choices():
    from fly_golf.training.pipeline import CV_FOLDS, _k_choices, _stratified_folds

    labels = np.array([True] * 6 + [False] * 40)
    folds = _stratified_folds(labels, 0)
    for k in range(CV_FOLDS):  # every training fold sees both classes
        assert labels[folds != k].any() and (~labels[folds != k]).any() and labels[folds == k].any()
    assert _k_choices(481) == [4, 8, 16, 32, 64]  # review finding: 64 used to be tried twice
    assert _k_choices(64) == [4, 8, 16, 32, 64] and _k_choices(14) == [4, 8, 14]


def test_bench_needs_at_least_one_round():
    from fly_golf.experiments.bench import bench

    with pytest.raises(ValueError):
        bench("mock", rounds=0, log=lambda m: None)
    assert summarize_rounds([]) == {"rounds": 0}


def test_a_v1_readout_still_plays(synthetic_graph):
    from fly_golf.brain.malecns.controller import MaleCNSController

    names = [str(n) for n in MaleCNSController(synthetic_graph).feature_names]
    f = len(names)
    v1 = LinearReadout(names, np.zeros(f), np.ones(f), np.zeros((3, f)), np.array([0.0, 0.4, 0.0]))
    c = TrainedReadoutController(synthetic_graph, v1)
    s = PuttingSession(c)
    s.new_hole(2)
    rec = s.play_shot()
    assert rec["controller"]["id"] == "malecns-trained" and rec["motor"]["channels"]["stroke_power"] == 0.4


def test_bench_round_is_complete_and_reproducible():
    from fly_golf.brain.mock import MockBrainController

    a = play_round(3, MockBrainController())
    assert len(a["card"]) == 9 and all(c["strokes"] is not None for c in a["card"])
    assert a == play_round(3, MockBrainController())
    sm = summarize_rounds([a])
    assert sm["rounds"] == 1 and sm["mean_strokes"] == a["strokes"] and sm["by_distance"]
