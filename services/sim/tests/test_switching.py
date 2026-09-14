"""Swapping the brain mid-round: the round goes on, and every record says who played."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fly_golf.api.app import create_app
from fly_golf.brain.malecns.controller import MaleCNSController
from fly_golf.brain.mock import MockBrainController
from fly_golf.config import Settings
from fly_golf.experiments.runner import PuttingSession, RoundSession, RunRecorder, list_runs


def test_round_session_records_who_played_each_hole(synthetic_graph, tmp_path):
    rec = RunRecorder(tmp_path / "runs")
    s = RoundSession(MockBrainController(), recorder=rec)
    s.new_round(5, start_hole=6)
    first = s.play_shot()
    ball, strokes = list(s.env.ball), s.env.strokes
    s.set_controller(MaleCNSController(synthetic_graph))
    state = s.state()
    assert state["ball"] == ball and state["strokes"] == strokes and state["hole_number"] == 6
    assert state["controller"]["id"] == "malecns"
    second = s.play_shot()
    assert first["controller"]["id"] == "mock" and second["controller"]["id"] == "malecns"
    assert second["initial_state"]["ball"] == ball
    assert s.state()["scorecard"][5]["controllers"] == ["mock", "malecns"]
    assert s.state()["controllers_used"] == ["mock", "malecns"]
    meta = json.loads((rec.dir / "run.json").read_text())
    assert meta["controllers_used"] == ["mock", "malecns"]
    assert list_runs(tmp_path / "runs")[0]["controllers_used"] == ["mock", "malecns"]
    # A fresh round starts with a clean card.
    s.new_round(6)
    assert s.state()["controllers_used"] == [] and all(c["controllers"] == [] for c in s.state()["scorecard"])


def test_putting_session_switch_keeps_the_green(synthetic_graph):
    s = PuttingSession(MockBrainController())
    s.new_hole(3)
    s.play_shot()
    if s.env.done:
        s.new_hole(4)
    ball = list(s.env.ball)
    s.set_controller(MaleCNSController(synthetic_graph))
    assert s.state()["ball"] == ball
    s.play_shot()
    assert s.state()["controllers_used"][-1] == "malecns"


def test_a_brain_that_fails_is_not_credited_with_the_hole():
    class Broken(MockBrainController):
        def step(self, duration_ms):
            raise RuntimeError("no brain today")

    s = RoundSession(Broken())
    s.new_round(1)
    with pytest.raises(RuntimeError):
        s.play_shot()
    assert s.state()["scorecard"][0]["controllers"] == [] and s.state()["controllers_used"] == []


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        repo_root=Path(__file__).resolve().parents[3],
        data_dir=tmp_path / "nodata",
        runs_dir=tmp_path / "runs",
        api_host="127.0.0.1",
        api_port=0,
        detailed_traces=False,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_api_switch_keeps_the_round_and_refuses_unavailable(client):
    client.post("/api/session", json={"controller": "mock", "seed": 4, "mode": "course"})
    shot = client.post("/api/shot").json()
    before = client.get("/api/status").json()["session"]
    # No connectome in CI: switching to it is refused, and the round is untouched (never faked).
    r = client.post("/api/controller", json={"controller": "malecns"})
    assert r.status_code == 409
    after = client.get("/api/status").json()
    assert after["active_controller"] == "mock"
    assert after["session"]["ball"] == before["ball"] and after["session"]["strokes"] == before["strokes"]
    ok = client.post("/api/controller", json={"controller": "mock"}).json()
    assert ok["hole_number"] == 1 and ok["strokes"] == before["strokes"] and ok["run_id"] == shot["run_id"]
    assert ok["scorecard"][0]["controllers"] == ["mock"] and ok["controllers_used"] == ["mock"]
    assert client.post("/api/controller", json={"controller": "nope"}).status_code == 422


def test_api_switch_is_refused_while_busy(client):
    class Held:  # stands in for the service lock while a shot / reset / brain load holds it
        def locked(self) -> bool:
            return True

    client.app.state.service.lock = Held()
    r = client.post("/api/controller", json={"controller": "mock"})
    assert r.status_code == 409 and "busy" in r.json()["detail"]["message"]
