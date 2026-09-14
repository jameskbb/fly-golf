import json

import pytest

from fly_golf.brain.mock import MockBrainController
from fly_golf.experiments.runner import (
    PuttingSession,
    RunRecorder,
    list_runs,
    load_run,
    replay_controller,
    replay_physics,
)

REQUIRED_FIELDS = {
    "experiment_id",
    "run_id",
    "shot_id",
    "timestamp_utc",
    "git",
    "seed",
    "controller",
    "versions",
    "scenario",
    "initial_state",
    "sensory",
    "neural_summary",
    "motor",
    "stroke",
    "trajectory",
    "outcome",
    "reward",
    "wall_duration_s",
    "sim_duration_s",
    "controller_seed",
}


@pytest.fixture
def session(tmp_path):
    rec = RunRecorder(tmp_path, metadata={"controller": "mock"})
    return PuttingSession(MockBrainController(), recorder=rec), tmp_path


def test_complete_automated_putt(session):
    s, _ = session
    s.new_hole(7)
    record = s.play_shot()
    assert set(record) >= REQUIRED_FIELDS
    assert record["controller"]["is_mock"] is True
    assert record["neural_summary"] is None
    assert len(record["trajectory"]["points"]) >= 1
    assert record["outcome"]["outcome"] in {"holed", "stopped", "off_green", "no_contact", "timeout"}


def test_play_hole_until_done(session):
    s, _ = session
    s.new_hole(11)
    shots = 0
    while s.env.state.value == "ready":
        s.play_shot()
        shots += 1
    assert 1 <= shots <= 6
    assert s.env.state.value in {"holed", "picked_up"}


def test_record_is_written_and_listed(session):
    s, runs_dir = session
    s.new_hole(3)
    s.play_shot()
    runs = list_runs(runs_dir)
    assert len(runs) == 1 and runs[0]["shots"] == 1
    loaded = load_run(runs_dir, s.recorder.run_id)
    assert loaded["shots"][0]["shot_id"] == "h000-s01"
    json.dumps(loaded)  # JSON-serializable


def test_load_run_rejects_path_traversal(tmp_path):
    assert load_run(tmp_path, "../etc") is None


def test_replay_reproduces_identical_trajectory(session):
    s, runs_dir = session
    s.new_hole(21)
    s.play_shot()
    stored = load_run(runs_dir, s.recorder.run_id)["shots"][0]  # round-trip through JSON
    r = replay_physics(stored)
    assert r["identical"], r["max_abs_diff"]


def test_replay_reproduces_controller_output(session):
    s, runs_dir = session
    s.new_hole(21)
    s.play_shot()
    stored = load_run(runs_dir, s.recorder.run_id)["shots"][0]
    assert replay_controller(stored, MockBrainController())["identical"]


def test_same_seed_same_results(tmp_path):
    def play(seed):
        s = PuttingSession(MockBrainController())
        s.new_hole(seed)
        r = s.play_shot()
        return r["trajectory"]["points"], r["motor"]["channels"]

    assert play(99) == play(99)


def test_cannot_putt_after_hole_finished(session):
    s, _ = session
    s.new_hole(11)
    while s.env.state.value == "ready":
        s.play_shot()
    with pytest.raises(RuntimeError):
        s.play_shot()


def test_run_without_shots_creates_nothing_and_is_not_listed(tmp_path):
    rec = RunRecorder(tmp_path, metadata={"controller": "mock"})
    PuttingSession(MockBrainController(), recorder=rec).new_hole(1)
    assert not rec.dir.exists()
    assert list_runs(tmp_path) == []


def test_run_json_keeps_counts(session):
    s, runs_dir = session
    s.new_hole(11)
    while s.env.state.value == "ready":
        s.play_shot()
    listed = list_runs(runs_dir)[0]
    assert listed["shots"] == s.env.strokes
    assert listed["holed"] == int(s.env.state.value == "holed")


def test_records_capture_dirty_flag(session):
    s, _ = session
    s.new_hole(2)
    git = s.play_shot()["git"]
    assert set(git) >= {"commit", "dirty", "describe"}
