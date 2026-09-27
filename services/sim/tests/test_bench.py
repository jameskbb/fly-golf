"""`fly-golf bench` and `fly-golf round` on the 18-hole course (mock controller only, no connectome)."""

import json

from fly_golf.cli import main
from fly_golf.experiments.bench import BENCH_VERSION, bench, holes_for, play_round
from fly_golf.golf.course import HOLE_BY_NUMBER

SPLIT_KEYS = {
    "holes_covered",
    "par",
    "mean_strokes",
    "best",
    "holes_holed_pct",
    "holes_picked_up",
    "trees_per_round",
    "water_per_round",
}


def quiet(_line: str) -> None:
    pass


def test_bench_plays_eighteen_holes_with_nine_splits():
    report = bench("mock", rounds=2, seed0=100, log=quiet)
    assert report["bench"] == BENCH_VERSION == "eighteen-bench-v1"
    assert report["holes_covered"] == "1-18" and report["nine"] == "both"
    sm = report["summary"]
    assert sm["par"] == 72 and sm["holes"] == 36 and sm["holes_covered"] == "1-18"
    assert set(sm["nines"]) == {"front", "back"}
    for nid, split in sm["nines"].items():
        assert set(split) == SPLIT_KEYS and split["par"] == 36
        assert split["holes_covered"] == ("1-9" if nid == "front" else "10-18")
    assert sm["mean_strokes"] == round(sm["nines"]["front"]["mean_strokes"] + sm["nines"]["back"]["mean_strokes"], 2)
    for r in report["rounds"]:
        assert [c["hole"] for c in r["card"]] == list(range(1, 19))


def test_front_nine_bench_reproduces_the_front_of_an_eighteen_hole_round():
    assert holes_for("front") == tuple(range(1, 10)) and holes_for("back") == tuple(range(10, 19))
    from fly_golf.brain.mock import MockBrainController

    full = play_round(101, MockBrainController())
    front = play_round(101, MockBrainController(), nine="front")
    back = play_round(101, MockBrainController(), nine="back")
    assert front["card"] == full["card"][:9] and back["card"] == full["card"][9:]
    assert front["shots"] + back["shots"] == full["shots"]
    report = bench("mock", rounds=1, seed0=101, nine="front", log=quiet)
    sm = report["summary"]
    assert report["holes_covered"] == "1-9" and sm["par"] == 36 and set(sm["nines"]) == {"front"}
    assert sm["mean_strokes"] == front["strokes"]


def test_cli_bench_reports_splits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FLY_GOLF_RUNS_DIR", str(tmp_path / "runs"))
    out = tmp_path / "bench.json"
    args = ["bench", "--controller", "mock", "--rounds", "1", "--jobs", "1", "--out", str(out), "--nine", "back"]
    assert main(args) == 0
    report = json.loads(out.read_text())
    assert report["holes_covered"] == "10-18" and set(report["summary"]["nines"]) == {"back"}
    text = capsys.readouterr().out
    assert "holes 10-18" in text and "back nine" in text


def test_cli_round_plays_the_back_nine(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FLY_GOLF_RUNS_DIR", str(tmp_path / "runs"))
    assert main(["round", "--controller", "mock", "--seed", "7", "--first", "10", "--last", "18"]) == 0
    text = capsys.readouterr().out
    for n in range(10, 19):
        assert f"hole {n} '{HOLE_BY_NUMBER[n].name}'" in text
    assert "hole 9 " not in text and "over 9 holes" in text
    run_dir = next(p for p in (tmp_path / "runs").iterdir() if (p / "run.json").exists())
    rnd = json.loads((run_dir / "run.json").read_text())["round"]
    assert rnd["complete"] is True and rnd["holes"] == list(range(10, 19)) and len(rnd["scorecard"]) == 9
    assert main(["round", "--controller", "mock", "--first", "12", "--last", "11"]) == 2


def test_cli_replay_calls_front_nine_v2_records_compatible(tmp_path, monkeypatch, capsys):
    from fly_golf.brain.mock import MockBrainController
    from fly_golf.experiments.runner import RoundSession, RunRecorder

    runs = tmp_path / "runs"
    monkeypatch.setenv("FLY_GOLF_RUNS_DIR", str(runs))
    rec = RunRecorder(runs, metadata={"mode": "course"})
    s = RoundSession(MockBrainController(), recorder=rec)
    s.new_round(4, start_hole=5)
    while not s.env.done:
        s.play_shot()
    path = runs / rec.run_id / "shots.jsonl"
    shots = [json.loads(line) for line in path.read_text().splitlines()]
    for shot in shots:
        shot["course"]["version"] = shot["versions"]["course"] = "front-nine-v2"
    path.write_text("".join(json.dumps(shot) + "\n" for shot in shots))
    assert main(["replay", rec.run_id, "--controller"]) == 0
    text = capsys.readouterr().out
    assert text.count("trajectory identical=True") == len(shots)
    assert "course front-nine-v2: hole geometry unchanged in eighteen-v1, compatible" in text
    assert "WARNING" not in text


def test_attach_writes_the_holes_label_for_the_web(tmp_path, monkeypatch):
    # --attach needs the trained controller (and so the connectome); check the metadata it builds
    # through the same code path with the graph loader and bench stubbed out.
    import fly_golf.cli as cli
    import fly_golf.experiments.bench as bench_mod

    readout = tmp_path / "readout.json"
    readout.write_text(json.dumps({"meta": {"id": "r"}}))
    monkeypatch.setenv("FLY_GOLF_RUNS_DIR", str(tmp_path / "runs"))
    real = bench_mod.bench

    def fake_bench(controller_id, **kw):
        kw.pop("graph", None), kw.pop("readout_path", None)
        return real("mock", **kw, log=quiet)

    monkeypatch.setattr(bench_mod, "bench", fake_bench)
    monkeypatch.setattr("fly_golf.brain.malecns.graph.load_compiled", lambda _p: None)
    args = ["bench", "--controller", "malecns-trained", "--readout", str(readout), "--attach", "--rounds", "1"]
    assert cli.main([*args, "--jobs", "1", "--out", str(tmp_path / "b.json")]) == 0
    b = json.loads(readout.read_text())["meta"]["bench"]
    assert b["holes"] == b["holes_covered"] == "1-18" and b["par"] == 72
    assert set(b["nines"]) == {"front", "back"} and b["nines"]["back"]["mean_strokes"] > 0
    assert b["mean_strokes"] == round(b["nines"]["front"]["mean_strokes"] + b["nines"]["back"]["mean_strokes"], 2)
    for k in ("rounds", "best_round", "holes_holed_pct", "trees_per_round", "water_per_round", "bench", "seeds"):
        assert k in b
