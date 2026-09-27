"""The static showcase exporter (fly_golf.experiments.showcase) and the committed showcase files."""

import hashlib
import json
from pathlib import Path

import pytest

from fly_golf.api.schemas import ShotRecordModel
from fly_golf.brain.mock import MockBrainController
from fly_golf.cli import main
from fly_golf.experiments.runner import PuttingSession, RoundSession, RunRecorder
from fly_golf.experiments.showcase import (
    REMOVED_PATH,
    SHOWCASE_FORMAT,
    ShowcaseExportError,
    export_showcase,
    scorecard_from_shots,
)
from fly_golf.golf.payload import course_payload

COMMITTED = Path(__file__).resolve().parents[3] / "apps" / "web" / "public" / "showcase"
# Real records made before the back nine existed: holes 1, 3 and 8 of the committed front-nine-v2
# showcase round mock-front-nine-s07 (from git history), every stroke unchanged.
FRONT_NINE_V2 = Path(__file__).resolve().parent / "fixtures" / "front_nine_v2_mock_s07.json"
FRONT_NINE_V2_HOLES = [1, 3, 8]


def record_round(runs_dir: Path, holes: int = 2, seed: int = 3) -> str:
    rec = RunRecorder(runs_dir, metadata={"mode": "course"})
    session = RoundSession(MockBrainController(), recorder=rec)
    session.new_round(seed)
    for i in range(holes):
        while not session.env.done:
            session.play_shot()
        if i < holes - 1:
            session.next_hole()
    return rec.run_id


def digests(directory: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir()) if p.is_file()}


@pytest.fixture
def run(tmp_path):
    runs = tmp_path / "runs"
    return runs, record_round(runs)


def test_export_writes_a_browser_ready_showcase(run, tmp_path):
    runs, run_id = run
    out = tmp_path / "showcase"
    report = export_showcase(runs, run_id, out, slug="mock-two-holes", title="Mock - two holes")
    index = json.loads((out / "index.json").read_text())
    assert index["format"] == SHOWCASE_FORMAT and index["featured"] == "mock-two-holes"
    [entry] = index["runs"]
    doc = json.loads((out / entry["file"]).read_text())
    recorded = [json.loads(line) for line in (runs / run_id / "shots.jsonl").read_text().splitlines()]
    assert entry["shots"] == len(doc["shots"]) == len(recorded) == report["shots"]
    assert entry["is_mock"] is True and entry["controller"]["label"] == "MOCK CONTROLLER"
    assert entry["holes_played"] == 2 and doc["round"]["holes_played"] == 2
    # the rebuilt scorecard is the recorder's own
    meta = json.loads((runs / run_id / "run.json").read_text())
    assert [(c["hole"], c["strokes"], c["holed"]) for c in doc["round"]["scorecard"]] == [
        (c["hole"], c["strokes"], c["holed"]) for c in meta["round"]["scorecard"]
    ]
    for shot, original in zip(doc["shots"], recorded, strict=True):
        ShotRecordModel.model_validate(shot)
        assert shot["shot_id"] == original["shot_id"] and shot["motor"] == original["motor"]
        assert shot["outcome"] == original["outcome"]
        assert all(v == round(v, 4) for p in shot["trajectory"]["points"] for v in p)
        assert len(shot["trajectory"]["points"]) == len(original["trajectory"]["points"])
    assert json.loads((out / "course.json").read_text()) == json.loads(json.dumps(course_payload()))
    assert report["run_bytes"] == (out / entry["file"]).stat().st_size


def test_export_never_modifies_the_run(run, tmp_path):
    runs, run_id = run
    before = digests(runs / run_id)
    export_showcase(runs, run_id, tmp_path / "out", slug="x", title="Mock")
    assert digests(runs / run_id) == before
    with pytest.raises(ShowcaseExportError, match="inside the run directory"):
        export_showcase(runs, run_id, runs / run_id / "showcase", slug="x", title="Mock")


def test_export_refuses_a_mock_run_titled_as_malecns(run, tmp_path):
    runs, run_id = run
    with pytest.raises(ShowcaseExportError, match="MOCK"):
        export_showcase(runs, run_id, tmp_path / "out", slug="x", title="Trained MaleCNS - Front Nine")
    export_showcase(runs, run_id, tmp_path / "out", slug="x", title="MaleCNS vs mock: the mock round")


def test_export_refuses_a_malecns_shot_without_neural_activity(run, tmp_path):
    runs, run_id = run
    path = runs / run_id / "shots.jsonl"
    shots = [json.loads(line) for line in path.read_text().splitlines()]
    shots[0]["controller"].update(kind="malecns", is_mock=False, id="malecns")
    path.write_text("".join(json.dumps(s) + "\n" for s in shots))
    with pytest.raises(ShowcaseExportError, match="without recorded neural activity"):
        export_showcase(runs, run_id, tmp_path / "out", slug="x", title="Mixed")


def test_export_removes_local_paths(run, tmp_path):
    runs, run_id = run
    path = runs / run_id / "shots.jsonl"
    shots = [json.loads(line) for line in path.read_text().splitlines()]
    shots[0]["trace_file"] = "some/trace.json"
    shots[0]["controller"]["config"] = {"readout": {"report": "/Users/someone/runs/bench/x.json", "id": "r1"}}
    path.write_text("".join(json.dumps(s) + "\n" for s in shots))
    report = export_showcase(runs, run_id, tmp_path / "out", slug="x", title="Mock")
    doc = json.loads(Path(report["run_file"]).read_text())
    assert "trace_file" not in doc["shots"][0]
    assert doc["shots"][0]["controller"]["config"]["readout"] == {"report": REMOVED_PATH, "id": "r1"}
    assert any("local file path" in n for n in report["notes"])
    assert "/Users/someone" not in Path(report["run_file"]).read_text()


def test_export_rejects_bad_input(run, tmp_path):
    runs, run_id = run
    out = tmp_path / "out"
    with pytest.raises(ShowcaseExportError, match="not found"):
        export_showcase(runs, "no-such-run", out, slug="x", title="Mock")
    with pytest.raises(ShowcaseExportError, match="slug"):
        export_showcase(runs, run_id, out, slug="Bad Slug", title="Mock")
    with pytest.raises(ShowcaseExportError, match="round seed"):
        export_showcase(runs, run_id, out, slug="x", title="Mock", round_seed=999)
    rec = RunRecorder(runs)
    putting = PuttingSession(MockBrainController(), recorder=rec)
    putting.new_hole(5)
    putting.play_shot()
    with pytest.raises(ShowcaseExportError, match="practice-green"):
        export_showcase(runs, rec.run_id, out, slug="x", title="Mock")


def test_index_keeps_other_runs_and_the_featured_one(tmp_path):
    runs = tmp_path / "runs"
    first, second = record_round(runs, holes=1, seed=4), record_round(runs, holes=1, seed=5)
    out = tmp_path / "out"
    export_showcase(runs, first, out, slug="a", title="Mock A")
    export_showcase(runs, second, out, slug="b", title="Mock B")
    index = json.loads((out / "index.json").read_text())
    assert [r["id"] for r in index["runs"]] == ["a", "b"] and index["featured"] == "a"
    export_showcase(runs, second, out, slug="b", title="Mock B again", featured=True)
    index = json.loads((out / "index.json").read_text())
    assert [r["title"] for r in index["runs"]] == ["Mock A", "Mock B again"] and index["featured"] == "b"


def test_cli_export_showcase(run, tmp_path, monkeypatch, capsys):
    runs, run_id = run
    monkeypatch.setenv("FLY_GOLF_RUNS_DIR", str(runs))
    out = tmp_path / "cli-out"
    assert main(["export-showcase", run_id, "--slug", "cli", "--title", "Mock", "--out", str(out)]) == 0
    assert (out / "runs" / "cli.json").exists() and "MB" in capsys.readouterr().out
    assert main(["export-showcase", run_id, "--slug", "cli", "--title", "MaleCNS round", "--out", str(out)]) == 2


def test_export_an_eighteen_hole_round(tmp_path):
    runs = tmp_path / "runs"
    run_id = record_round(runs, holes=18, seed=7)
    out = tmp_path / "out"
    report = export_showcase(runs, run_id, out, slug="mock-eighteen-s07", title="Mock - 18 holes")
    rnd = report["round"]
    assert rnd["complete"] and rnd["holes_played"] == 18 and len(rnd["scorecard"]) == 18
    assert [c["hole"] for c in rnd["scorecard"]] == list(range(1, 19))
    doc = json.loads((out / "runs" / "mock-eighteen-s07.json").read_text())
    assert doc["course_version"] == "eighteen-v1"
    assert "front-nine" not in doc["description"] and "front nine" not in doc["description"]
    course = json.loads((out / "course.json").read_text())
    assert (
        course["par"] == 72 and len(course["holes"]) == 18 and [n["id"] for n in course["nines"]] == ["front", "back"]
    )
    index = json.loads((out / "index.json").read_text())
    assert index["runs"][0]["holes_played"] == 18 and index["runs"][0]["round_complete"] is True
    assert index["runs"][0]["holes"] == doc["holes"] == list(range(1, 19))
    assert index["runs"][0]["course_version"] == "eighteen-v1"


def front_nine_v2_run(runs_dir: Path) -> str:
    """A run as main's code (front-nine-v2) wrote it: real shots from the front-nine-v2 fixture, with
    its recorded scorecard in run.json and no "holes" (front-nine-v2 rounds had none)."""
    doc = json.loads(FRONT_NINE_V2.read_text())
    rnd = dict(doc["round"])
    assert "holes" not in rnd and [c["hole"] for c in rnd["scorecard"]] == FRONT_NINE_V2_HOLES
    run_id = "20260901T000000Z-f9v2"
    d = runs_dir / run_id
    d.mkdir(parents=True)
    meta = {"record_type": "run", "run_id": run_id, "mode": "course", "round": rnd, "rounds": [rnd]}
    meta["versions"] = doc["source"]["versions"]
    (d / "run.json").write_text(json.dumps(meta))
    (d / "shots.jsonl").write_text("".join(json.dumps(shot) + "\n" for shot in doc["shots"]))
    return run_id


def test_front_nine_v2_fixture_is_real_old_data():
    doc = json.loads(FRONT_NINE_V2.read_text())
    assert doc["course_version"] == "front-nine-v2" and len(doc["shots"]) >= 10
    assert sorted({s["course"]["hole_number"] for s in doc["shots"]}) == FRONT_NINE_V2_HOLES
    for shot in doc["shots"]:
        ShotRecordModel.model_validate(shot)
        assert shot["versions"]["course"] == "front-nine-v2" and "holes" not in shot["course"]


def test_export_a_real_front_nine_v2_run(tmp_path):
    runs = tmp_path / "runs"
    run_id = front_nine_v2_run(runs)
    meta = json.loads((runs / run_id / "run.json").read_text())
    assert meta["versions"]["course"] == "front-nine-v2"
    out = tmp_path / "out"
    report = export_showcase(runs, run_id, out, slug="mock-front-nine-s07", title="Mock - front nine")
    rnd = report["round"]
    assert rnd["complete"] and rnd["holes"] == FRONT_NINE_V2_HOLES and len(rnd["scorecard"]) == 3
    assert [(c["hole"], c["strokes"]) for c in rnd["scorecard"]] == [
        (c["hole"], c["strokes"]) for c in meta["round"]["scorecard"]
    ]
    [entry] = json.loads((out / "index.json").read_text())["runs"]
    doc = json.loads((out / entry["file"]).read_text())
    for d in (entry, doc):
        assert d["holes"] == FRONT_NINE_V2_HOLES
        assert d["course_version"] == "front-nine-v2" and d["course_version_exported_with"] == "eighteen-v1"
    assert entry["round_complete"] is True
    # A wrong recorded scorecard is still caught, hole by hole.
    meta["round"]["scorecard"][1]["strokes"] += 1
    meta["rounds"] = [meta["round"]]
    (runs / run_id / "run.json").write_text(json.dumps(meta))
    with pytest.raises(ShowcaseExportError, match="does not match"):
        export_showcase(runs, run_id, tmp_path / "out2", slug="x", title="Mock")


def test_export_refuses_an_incompatible_course_version(run, tmp_path):
    runs, run_id = run
    path = runs / run_id / "shots.jsonl"
    shots = [json.loads(line) for line in path.read_text().splitlines()]
    shots[0]["versions"]["course"] = "front-nine-v1"
    path.write_text("".join(json.dumps(s) + "\n" for s in shots))
    with pytest.raises(ShowcaseExportError, match="wrong holes"):
        export_showcase(runs, run_id, tmp_path / "out", slug="old", title="Mock")


def test_export_a_back_nine_round_is_complete(tmp_path):
    runs = tmp_path / "runs"
    rec = RunRecorder(runs, metadata={"mode": "course"})
    session = RoundSession(MockBrainController(), recorder=rec)
    session.new_round(9, holes=range(10, 19))
    while True:
        while not session.env.done:
            session.play_shot()
        if session.round_complete:
            break
        session.next_hole()
    report = export_showcase(runs, rec.run_id, tmp_path / "out", slug="mock-back", title="Mock - back nine")
    assert report["round"]["complete"] and report["round"]["holes"] == list(range(10, 19))
    [entry] = json.loads((tmp_path / "out" / "index.json").read_text())["runs"]
    assert entry["round_complete"] is True and entry["holes"] == list(range(10, 19))
    assert entry["course_version"] == "eighteen-v1" and "course_version_exported_with" not in entry


@pytest.mark.skipif(not (COMMITTED / "index.json").exists(), reason="no showcase committed")
def test_committed_showcase_is_valid_and_matches_the_code():
    index = json.loads((COMMITTED / "index.json").read_text())
    assert index["format"] == SHOWCASE_FORMAT and index["runs"]
    assert index["featured"] in {r["id"] for r in index["runs"]}
    # the course the showcase draws is the course this code plays
    committed = json.loads((COMMITTED / index["course"]).read_text())
    assert committed == json.loads(json.dumps(course_payload()))
    for entry in index["runs"]:
        doc = json.loads((COMMITTED / entry["file"]).read_text())
        assert doc["id"] == entry["id"] and len(doc["shots"]) == entry["shots"]
        for shot in doc["shots"]:
            ShotRecordModel.model_validate(shot)
            if not shot["controller"]["is_mock"]:
                assert shot["neural_summary"]["neuron_count"] > 0
        assert entry["is_mock"] == any(s["controller"]["is_mock"] for s in doc["shots"])
        recorded = {c["hole"]: c["strokes"] for c in doc["round"]["scorecard"]}
        card = scorecard_from_shots(doc["shots"], sorted(recorded))
        assert {c["hole"]: c["strokes"] for c in card} == recorded
