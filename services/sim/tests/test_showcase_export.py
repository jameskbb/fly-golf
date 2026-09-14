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
    shots[0]["controller"]["config"] = {"readout": {"report": "/home/someone/runs/bench/x.json", "id": "r1"}}
    path.write_text("".join(json.dumps(s) + "\n" for s in shots))
    report = export_showcase(runs, run_id, tmp_path / "out", slug="x", title="Mock")
    doc = json.loads(Path(report["run_file"]).read_text())
    assert "trace_file" not in doc["shots"][0]
    assert doc["shots"][0]["controller"]["config"]["readout"] == {"report": REMOVED_PATH, "id": "r1"}
    assert any("local file path" in n for n in report["notes"])
    assert "/home/someone" not in Path(report["run_file"]).read_text()


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


@pytest.mark.skipif(not (COMMITTED / "index.json").exists(), reason="no showcase committed")
def test_committed_showcase_is_valid_and_matches_the_code():
    index = json.loads((COMMITTED / "index.json").read_text())
    assert index["format"] == SHOWCASE_FORMAT and index["runs"]
    assert index["featured"] in {r["id"] for r in index["runs"]}
    # the course the showcase draws is the course this code plays
    assert json.loads((COMMITTED / index["course"]).read_text()) == json.loads(json.dumps(course_payload()))
    for entry in index["runs"]:
        doc = json.loads((COMMITTED / entry["file"]).read_text())
        assert doc["id"] == entry["id"] and len(doc["shots"]) == entry["shots"]
        for shot in doc["shots"]:
            ShotRecordModel.model_validate(shot)
            if not shot["controller"]["is_mock"]:
                assert shot["neural_summary"]["neuron_count"] > 0
        assert entry["is_mock"] == any(s["controller"]["is_mock"] for s in doc["shots"])
        card = scorecard_from_shots(doc["shots"])
        assert [(c["hole"], c["strokes"]) for c in card] == [
            (c["hole"], c["strokes"]) for c in doc["round"]["scorecard"]
        ]
