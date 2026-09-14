import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fly_golf import PROTOCOL_VERSION
from fly_golf.api.app import create_app
from fly_golf.api.schemas import Envelope, ErrorData, ServerHello, ShotRecordModel
from fly_golf.config import Settings

FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "protocol" / "fixtures"


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


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["protocol_version"] == PROTOCOL_VERSION


def test_status_reports_malecns_unavailable_without_data(client):
    s = client.get("/api/status").json()
    assert s["active_controller"] == "mock"
    assert s["malecns"]["status"] == "unavailable"
    assert s["malecns"]["fix_command"] == "make data"


def test_selecting_unavailable_malecns_is_refused_not_faked(client):
    r = client.post("/api/session", json={"controller": "malecns"})
    assert r.status_code == 409
    assert client.get("/api/status").json()["active_controller"] == "mock"


def test_session_putt_runs_and_replay(client):
    state = client.post("/api/session", json={"controller": "mock", "seed": 12, "mode": "practice"}).json()
    assert state["scenario"]["seed"] == 12
    rec = client.post("/api/putt").json()
    ShotRecordModel.model_validate(rec)
    assert rec["controller"]["label"] == "MOCK CONTROLLER"
    runs = client.get("/api/runs").json()["runs"]
    assert any(r["run_id"] == rec["run_id"] for r in runs)
    run = client.get(f"/api/runs/{rec['run_id']}").json()
    assert run["shots"][0]["shot_id"] == rec["shot_id"]
    rep = client.get(f"/api/runs/{rec['run_id']}/shots/{rec['shot_id']}/replay").json()
    assert rep["replay"]["identical"] is True


def test_course_mode_round_flow(client):
    state = client.post("/api/session", json={"controller": "mock", "seed": 4, "mode": "course"}).json()
    assert state["mode"] == "course" and state["hole_number"] == 1 and len(state["scorecard"]) == 9
    assert state["hole"]["par"] == 4 and state["hole"]["trees"]
    assert client.post("/api/next").status_code == 409  # hole 1 still in play
    rec = client.post("/api/shot").json()
    ShotRecordModel.model_validate(rec)
    assert rec["mode"] == "course" and rec["stroke"]["club"]["id"] != "putter"
    rep = client.get(f"/api/runs/{rec['run_id']}/shots/{rec['shot_id']}/replay").json()
    assert rep["replay"]["identical"] is True
    six = client.post("/api/reset", json={"hole": 6}).json()
    assert six["hole_number"] == 6 and six["round_seed"] == 4
    course = client.get("/api/course").json()
    assert len(course["holes"]) == 9 and len(course["clubs"]) == 14 and course["par"] == 36


def test_trained_controller_unavailable_without_data(client):
    ids = {c["id"]: c for c in client.get("/api/status").json()["controllers"]}
    assert ids["malecns-trained"]["available"] is False
    assert client.post("/api/session", json={"controller": "malecns-trained"}).status_code == 409


def test_reset_with_seed(client):
    a = client.post("/api/reset", json={"seed": 5}).json()
    b = client.post("/api/reset", json={"seed": 5}).json()
    assert a["scenario"] == b["scenario"]


def test_bad_seed_rejected(client):
    assert client.post("/api/reset", json={"seed": -1}).status_code == 422


def test_websocket_handshake_and_stream(client):
    with client.websocket_connect("/ws/simulation") as ws:
        hello = Envelope.model_validate(ws.receive_json())
        assert hello.type == "hello"
        ServerHello.model_validate(hello.data)
        ws.send_json(
            {
                "type": "hello",
                "protocol_version": PROTOCOL_VERSION,
                "seq": 0,
                "data": {"client": "pytest", "protocol_version": PROTOCOL_VERSION},
            }
        )
        state = ws.receive_json()
        assert state["type"] == "state"
        client.post("/api/putt")
        types = set()
        for _ in range(12):
            msg = ws.receive_json()
            types.add(msg["type"])
            if msg["type"] == "shot_result":
                ShotRecordModel.model_validate(msg["data"])
                break
        assert "shot_phase" in types and "shot_result" in types


def test_websocket_version_mismatch_is_reported(client):
    with client.websocket_connect("/ws/simulation") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "hello",
                "protocol_version": 999,
                "seq": 0,
                "data": {"client": "old", "protocol_version": 999},
            }
        )
        err = ws.receive_json()
        assert err["type"] == "error"
        data = ErrorData.model_validate(err["data"])
        assert data.code == "protocol_mismatch"


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")) if FIXTURES.exists() else [])
def test_shared_protocol_fixtures_validate(name):
    msg = json.loads((FIXTURES / name).read_text())
    env = Envelope.model_validate(msg)
    assert env.protocol_version == PROTOCOL_VERSION
    if env.type == "hello" and "server" in env.data:
        ServerHello.model_validate(env.data)
    if env.type == "error":
        ErrorData.model_validate(env.data)
    if env.type == "shot_result":
        ShotRecordModel.model_validate(env.data)


def test_websocket_non_hello_first_message_is_bad_request(client):
    with client.websocket_connect("/ws/simulation") as ws:
        ws.receive_json()
        ws.send_json({"type": "state", "protocol_version": PROTOCOL_VERSION, "seq": 0, "data": {}})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert ErrorData.model_validate(err["data"]).code == "bad_request"


def test_websocket_disconnect_before_hello_is_quiet(client):
    with client.websocket_connect("/ws/simulation") as ws:
        ws.receive_json()
    assert client.get("/health").json()["status"] == "ok"
