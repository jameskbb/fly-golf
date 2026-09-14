"""Export a recorded run as a static showcase for the web app (GitHub Pages).

The showcase is how https://jameskbb.github.io/fly-golf/ replays real Fly Golf rounds without the
Python backend. Nothing is simulated or invented here: every shot in the output is a recorded
ShotRecord from ``runs/<run_id>/shots.jsonl``, validated, stripped of machine-local fields and
written as browser-ready JSON. The original run is only read, never modified, and no connectome
data is involved.

Output layout (``apps/web/public/showcase/`` by default; schemas in
``packages/protocol/src/showcase.ts``)::

    index.json          the available showcase runs (format ``fly-golf-showcase`` v1)
    course.json         the course geometry and the bag, shared by every run
    runs/<slug>.json    one exported round: its shots, scorecard, controller and provenance
"""

from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ..api.schemas import ShotRecordModel
from ..golf.course import COURSE_VERSION, FRONT_NINE
from ..golf.payload import course_payload
from .runner import load_run

SHOWCASE_FORMAT = "fly-golf-showcase"
SHOWCASE_VERSION = 1
EXPORTER_VERSION = "fly-golf-showcase-export-v1"
TRAJECTORY_DECIMALS = 4  # 0.1 mm and 0.1 ms: far below what the replay can show
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LOCAL_PATH_RE = re.compile(r"^(/|~/|[A-Za-z]:[\\/])\S*[\\/]")
REMOVED_PATH = "<local path removed>"
LOCAL_FIELDS = ("trace_file",)  # per-shot fields that only mean something on the recording machine
CLAIMS_CONNECTOME = re.compile(r"male\s*-?cns|connectome", re.IGNORECASE)
ADMITS_MOCK = re.compile(r"mock|mixed", re.IGNORECASE)
SUMMARY_CONTROLLER_KEYS = ("id", "kind", "label", "is_mock", "neuron_count", "edge_count", "connectome", "model")


class ShowcaseExportError(ValueError):
    """The run cannot be exported honestly: missing, invalid, or not what its title says."""


def _hole(shot: dict) -> int:
    return int((shot.get("course") or {}).get("hole_number") or (shot.get("hole") or {}).get("number") or 0)


def _round_seed(shot: dict):
    return (shot.get("course") or {}).get("round_seed")


def _attempt(shot: dict) -> int:
    return int((shot.get("course") or {}).get("attempt") or 0)


def _scrub(value, removed: list[str]):
    """Replace absolute local file paths anywhere in a record."""
    if isinstance(value, dict):
        return {k: _scrub(v, removed) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, removed) for v in value]
    if isinstance(value, str) and LOCAL_PATH_RE.match(value):
        removed.append(value)
        return REMOVED_PATH
    return value


def scorecard_from_shots(shots: list[dict]) -> list[dict]:
    """The front-nine scorecard implied by a round's shots (the final attempt at each hole)."""
    card = {
        h.number: {"hole": h.number, "par": h.par, "strokes": None, "holed": None, "controllers": []}
        for h in FRONT_NINE
    }
    for shot in shots:
        entry = card[_hole(shot)]
        cid = shot["controller"]["id"]
        if cid not in entry["controllers"]:
            entry["controllers"].append(cid)
        if shot["outcome"]["episode_state"] != "ready":
            entry["strokes"] = int(shot["score"]["hole_strokes"])
            entry["holed"] = bool(shot["outcome"]["holed"])
    return [card[n] for n in sorted(card)]


def _round_summary(shots: list[dict], seed: int) -> dict:
    card = scorecard_from_shots(shots)
    played = [c for c in card if c["strokes"] is not None]
    strokes = sum(c["strokes"] for c in played)
    par = sum(c["par"] for c in played)
    used: list[str] = []
    for c in card:
        used += [cid for cid in c["controllers"] if cid not in used]
    return {
        "seed": seed,
        "complete": len(played) == len(card),
        "scorecard": card,
        "strokes": strokes,
        "par_played": par,
        "to_par": strokes - par,
        "holes_played": len(played),
        "controllers_used": used,
    }


def _recorded_round(meta: dict, seed: int) -> dict | None:
    found = None
    for r in [*(meta.get("rounds") or []), meta.get("round") or {}]:
        if r.get("seed") == seed:
            found = r
    return found


def _write_json(path: Path, obj, indent: int | None = None) -> int:
    text = json.dumps(
        obj, allow_nan=False, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")
    )
    data = (text + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    tmp.write_bytes(data)
    tmp.replace(path)
    return len(data)


def _load_index(path: Path) -> dict:
    if not path.exists():
        return {
            "format": SHOWCASE_FORMAT,
            "version": SHOWCASE_VERSION,
            "course": "course.json",
            "featured": None,
            "runs": [],
        }
    index = json.loads(path.read_text())
    if index.get("format") != SHOWCASE_FORMAT or index.get("version") != SHOWCASE_VERSION:
        raise ShowcaseExportError(f"{path} is not a {SHOWCASE_FORMAT} v{SHOWCASE_VERSION} index")
    return index


def export_showcase(
    runs_dir: Path,
    run_id: str,
    out_dir: Path,
    *,
    slug: str,
    title: str,
    description: str | None = None,
    round_seed: int | None = None,
    featured: bool = False,
) -> dict:
    """Export one round of a recorded run into ``out_dir``. Returns a report (paths, sizes, notes)."""
    if not SLUG_RE.match(slug):
        raise ShowcaseExportError(f"slug {slug!r} must be lower-case letters, digits and dashes")
    title = title.strip()
    if not title:
        raise ShowcaseExportError("a title is required")
    data = load_run(Path(runs_dir), run_id)
    if data is None:
        raise ShowcaseExportError(f"run {run_id!r} not found in {runs_dir}")
    run_dir = (Path(runs_dir) / run_id).resolve()
    out_dir = Path(out_dir)
    if out_dir.resolve().is_relative_to(run_dir):
        raise ShowcaseExportError("refusing to write the showcase inside the run directory")
    meta, shots = data["run"], data["shots"]
    if not shots:
        raise ShowcaseExportError(f"run {run_id} has no shots")

    problems = []
    for i, shot in enumerate(shots):
        try:
            ShotRecordModel.model_validate(shot)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            problems.append(f"shot {i} ({shot.get('shot_id', '?')}): {where}: {first['msg']}")
    if problems:
        raise ShowcaseExportError("invalid shot records:\n  " + "\n  ".join(problems))
    if any(s.get("mode") != "course" for s in shots):
        raise ShowcaseExportError("only front-nine course runs can be showcased; this run has practice-green shots")

    seeds = list(dict.fromkeys(_round_seed(s) for s in shots))
    if round_seed is None:
        if len(seeds) > 1:
            raise ShowcaseExportError(f"the run holds {len(seeds)} rounds (seeds {seeds}); choose one with --round")
        round_seed = seeds[0]
    elif round_seed not in seeds:
        raise ShowcaseExportError(f"round seed {round_seed} is not in this run (seeds {seeds})")
    shots = [s for s in shots if _round_seed(s) == round_seed]

    notes: list[str] = []
    final_attempt: dict[int, int] = {}
    for s in shots:
        final_attempt[_hole(s)] = max(final_attempt.get(_hole(s), 0), _attempt(s))
    kept = [s for s in shots if _attempt(s) == final_attempt[_hole(s)]]
    if len(kept) < len(shots):
        notes.append(
            f"{len(shots) - len(kept)} shot(s) from abandoned earlier attempts at a hole were left out; "
            "the scorecard counts the final attempt, as the app does"
        )
    shots = kept

    stale = sorted({str(s["versions"].get("course")) for s in shots} - {COURSE_VERSION})
    if stale:
        raise ShowcaseExportError(
            f"recorded on course {stale}, but this code builds {COURSE_VERSION}: the replay would draw the wrong holes"
        )

    ids = list(dict.fromkeys(s["controller"]["id"] for s in shots))
    n_mock = sum(1 for s in shots if s["controller"]["is_mock"])
    for s in shots:
        c = s["controller"]
        if c["is_mock"] != (c["kind"] == "mock"):
            raise ShowcaseExportError(
                f"{s['shot_id']}: controller kind {c['kind']!r} contradicts is_mock={c['is_mock']}"
            )
        if c["kind"] == "malecns" and not s.get("neural_summary"):
            raise ShowcaseExportError(
                f"{s['shot_id']}: a MaleCNS shot without recorded neural activity cannot be shown as connectome-driven"
            )
    if n_mock and CLAIMS_CONNECTOME.search(title) and not ADMITS_MOCK.search(title):
        raise ShowcaseExportError(
            f"the title {title!r} suggests a connectome run, but {n_mock} of {len(shots)} shots "
            "came from the MOCK controller"
        )

    commits = list(dict.fromkeys(s["git"]["commit"] for s in shots))
    dirty = any(s["git"].get("dirty") for s in shots)
    if len(commits) > 1:
        notes.append(f"recorded across {len(commits)} commits: {', '.join(c[:10] for c in commits)}")
    if dirty:
        notes.append("recorded from a working tree with uncommitted changes (git.dirty is true in the records)")

    removed: list[str] = []
    out_shots = []
    for s in shots:
        s = copy.deepcopy(s)
        for field in LOCAL_FIELDS:
            s.pop(field, None)
        s["trajectory"]["points"] = [[round(v, TRAJECTORY_DECIMALS) for v in p] for p in s["trajectory"]["points"]]
        out_shots.append(_scrub(s, removed))
    if removed:
        notes.append(f"{len(removed)} local file path(s) replaced with {REMOVED_PATH!r}")
    notes.append(
        f"trajectory samples rounded to {TRAJECTORY_DECIMALS} decimals (0.1 mm, 0.1 ms) for size; "
        f"the source run re-simulates bit for bit with `fly-golf replay {run_id}`"
    )

    rnd = _round_summary(out_shots, round_seed)
    recorded = _recorded_round(meta, round_seed)
    if recorded is not None:
        mine = [(c["hole"], c["strokes"], c["holed"]) for c in rnd["scorecard"]]
        theirs = [(c["hole"], c["strokes"], c["holed"]) for c in recorded.get("scorecard", [])]
        if mine != theirs:
            raise ShowcaseExportError("the scorecard rebuilt from the shots does not match the one the recorder wrote")

    first = out_shots[0]
    if len(ids) > 1:
        controller_summary = {"id": "mixed", "kind": "mock" if n_mock else "malecns", "label": "MIXED BRAINS"}
        controller_summary["is_mock"] = bool(n_mock)
    else:
        controller_summary = {k: first["controller"][k] for k in SUMMARY_CONTROLLER_KEYS if k in first["controller"]}
    label = controller_summary["label"]
    if description is None:
        description = (
            f"A recorded front-nine round played by the {label} controller (round seed {round_seed}). "
            "Every shot was simulated beforehand; this page replays the records."
        )
    recorded_utc = meta.get("created_utc") or first.get("timestamp_utc")
    doc = {
        "format": SHOWCASE_FORMAT,
        "version": SHOWCASE_VERSION,
        "id": slug,
        "title": title,
        "description": description,
        "source": {
            "run_id": meta.get("run_id", run_id),
            "experiment_id": meta.get("experiment_id") or first.get("experiment_id"),
            "created_utc": recorded_utc,
            "git": {"commit": first["git"]["commit"], "dirty": dirty},
            "versions": first["versions"],
        },
        "controller": first["controller"],
        "controllers_used": ids,
        "course_version": COURSE_VERSION,
        "round": rnd,
        "export": {
            "exporter": EXPORTER_VERSION,
            "exported_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "trajectory_decimals": TRAJECTORY_DECIMALS,
            "notes": notes,
        },
        "shots": out_shots,
    }
    summary = {
        "id": slug,
        "title": title,
        "description": description,
        "file": f"runs/{slug}.json",
        "controller": controller_summary,
        "controllers_used": ids,
        "is_mock": bool(n_mock),
        "mode": "course",
        "shots": len(out_shots),
        "holed": sum(1 for c in rnd["scorecard"] if c["holed"]),
        "holes_played": rnd["holes_played"],
        "strokes": rnd["strokes"],
        "to_par": rnd["to_par"],
        "round_complete": rnd["complete"],
        "round_seed": round_seed,
        "source_run_id": doc["source"]["run_id"],
        "recorded_utc": recorded_utc,
        "git_commit": first["git"]["commit"],
    }

    run_path = out_dir / summary["file"]
    run_bytes = _write_json(run_path, doc)
    course_bytes = _write_json(out_dir / "course.json", course_payload())
    index_path = out_dir / "index.json"
    index = _load_index(index_path)
    runs = index["runs"]
    for i, r in enumerate(runs):
        if r.get("id") == slug:
            runs[i] = summary
            break
    else:
        runs.append(summary)
    if featured or index.get("featured") not in {r.get("id") for r in runs}:
        index["featured"] = slug
    index_bytes = _write_json(index_path, index, indent=2)
    return {
        "run_file": str(run_path),
        "run_bytes": run_bytes,
        "course_bytes": course_bytes,
        "index_file": str(index_path),
        "index_bytes": index_bytes,
        "shots": len(out_shots),
        "controller": label,
        "round": rnd,
        "notes": notes,
    }
