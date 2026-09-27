"""No machine-local paths in readout metadata: what `fly-golf bench --attach` writes, and what is committed."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fly_golf.cli import portable_report_path

REPO = Path(__file__).resolve().parents[3]
READOUTS = REPO / "experiments" / "readouts"
LOCAL_DIR = re.compile(r"/(home|tmp)/")  # a home or temp directory anywhere in the string


def test_report_inside_runs_dir_is_named_runs_relative(tmp_path):
    repo, runs = tmp_path / "repo", tmp_path / "elsewhere" / "runs"
    out = runs / "bench" / "trained-18-s100.json"
    assert portable_report_path(out, repo, runs) == "runs/bench/trained-18-s100.json"


def test_report_inside_repo_is_repo_relative(tmp_path):
    repo, runs = tmp_path / "repo", tmp_path / "runs"
    out = repo / "experiments" / "bench" / "x.json"
    assert portable_report_path(out, repo, runs) == "experiments/bench/x.json"


def test_report_elsewhere_is_only_the_file_name(tmp_path):
    repo, runs = tmp_path / "repo", tmp_path / "repo" / "runs"
    out = tmp_path / "scratch" / "bench.json"
    got = portable_report_path(out, repo, runs)
    assert got == "bench.json"
    assert not got.startswith("/")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_committed_readouts_hold_no_local_paths():
    files = sorted(READOUTS.rglob("*.json"))
    assert files, "no readouts found"
    bad = []
    for f in files:
        for s in _strings(json.loads(f.read_text())):
            if s.startswith(("/", "~")) or LOCAL_DIR.search(s):
                bad.append(f"{f.relative_to(REPO)}: {s[:80]}")
    assert not bad, "machine-local paths in readouts:\n" + "\n".join(bad)
