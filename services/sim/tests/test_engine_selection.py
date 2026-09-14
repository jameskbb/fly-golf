"""Which neural engine runs what: new shots, trained readouts, replays. And the club chain
telemetry (senses -> activity -> readout -> club_reach -> club). Synthetic graph only."""

from __future__ import annotations

import numpy as np
import pytest

from fly_golf.brain.malecns.controller import MaleCNSController
from fly_golf.brain.malecns.engine import ENGINE_VERSION, LIFEngine, make_engine
from fly_golf.brain.malecns.legacy_engine import ENGINE_VERSION as LEGACY
from fly_golf.brain.malecns.legacy_engine import LIFEngine as LegacyLIFEngine
from fly_golf.brain.malecns.populations import decode_motor_v2
from fly_golf.brain.mock import MockBrainController
from fly_golf.brain.registry import ControllerRegistry
from fly_golf.brain.trained import HEADS, GatedReadout, TrainedReadoutController, readout_engine
from fly_golf.config import load_settings
from fly_golf.experiments.runner import RoundSession, replay_controller
from fly_golf.golf.clubs import BAG, club_from_reach, reach_for


def _readout(graph, meta: dict) -> GatedReadout:
    names = [str(n) for n in MaleCNSController(graph).feature_names]
    k = len(names)
    return GatedReadout(
        names,
        np.zeros(k),
        np.ones(k),
        np.zeros(k),
        -5.0,  # always swing
        np.zeros(k),
        4.0,  # always club index 4 (pitching wedge)
        {h: np.zeros((2, k)) for h in HEADS},
        {h: np.array([0.0, 0.6]) for h in HEADS},
        meta=meta,
    )


def test_new_shots_use_the_fly_golf_engine(synthetic_graph):
    c = MaleCNSController(synthetic_graph)
    assert isinstance(c.engine, LIFEngine) and c.info.model == ENGINE_VERSION == "fly-golf-lif-v1"
    assert c.info.config["engine"] == ENGINE_VERSION


def test_engines_by_version(synthetic_graph):
    g = synthetic_graph
    assert isinstance(make_engine(ENGINE_VERSION, g.ptr, g.post, g.weight), LIFEngine)
    assert isinstance(make_engine(LEGACY, g.ptr, g.post, g.weight), LegacyLIFEngine)
    with pytest.raises(ValueError, match="unknown neural engine"):
        make_engine("lif-imaginary-v9", g.ptr, g.post, g.weight)


def test_a_readout_runs_on_the_engine_it_was_trained_on(synthetic_graph):
    old = _readout(synthetic_graph, {"training_id": "old"})  # no engine recorded: pre-dates fly-golf-lif-v1
    new = _readout(synthetic_graph, {"training_id": "new", "neural_engine": ENGINE_VERSION})
    assert readout_engine(old.meta) == LEGACY and readout_engine(new.meta) == ENGINE_VERSION
    c_old = TrainedReadoutController(synthetic_graph, old)
    c_new = TrainedReadoutController(synthetic_graph, new)
    assert isinstance(c_old.engine, LegacyLIFEngine) and c_old.info.model == LEGACY
    assert isinstance(c_new.engine, LIFEngine) and c_new.info.model == ENGINE_VERSION
    assert c_old.info.config["readout"]["neural_engine"] == LEGACY
    assert c_old.info.config["readout"]["current_engine"] is False
    with pytest.raises(ValueError, match="refusing to run"):
        TrainedReadoutController(synthetic_graph, old, engine=ENGINE_VERSION)
    with pytest.raises(ValueError, match="refusing to run"):
        TrainedReadoutController(synthetic_graph, new, engine=LEGACY)


def test_replay_uses_the_recorded_engine(synthetic_graph):
    legacy = MaleCNSController(synthetic_graph, engine=LEGACY)
    session = RoundSession(legacy)
    session.new_round(3, start_hole=2)
    record = session.play_shot()
    assert record["controller"]["model"] == LEGACY
    registry = ControllerRegistry(load_settings())
    registry._graph = synthetic_graph  # the replay registry loads this graph instead of MaleCNS
    again = registry.replay_controller(record)
    assert isinstance(again.engine, LegacyLIFEngine)
    assert replay_controller(record, again)["identical"]
    assert registry.replay_controller(record) is again  # cached per (controller, engine, readout)


def test_replay_finds_archived_readouts(synthetic_graph, tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_GOLF_REPO_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    ro = _readout(synthetic_graph, {"training_id": "20990101T000000Z", "neural_engine": ENGINE_VERSION})
    ro.save(tmp_path / "experiments" / "readouts" / "archive" / "20990101T000000Z.json")
    c = TrainedReadoutController(synthetic_graph, ro, "experiments/readouts/archive/20990101T000000Z.json")
    s = RoundSession(c)
    s.new_round(5, start_hole=4)
    record = s.play_shot()
    registry = ControllerRegistry(load_settings())
    registry._graph = synthetic_graph
    replayed = registry.replay_controller(record)
    assert replay_controller(record, replayed)["identical"]
    record["controller"]["config"]["readout"]["id"] = "missing"
    with pytest.raises(FileNotFoundError, match="missing"):
        registry.replay_controller(record)


@pytest.mark.parametrize("controller", ["mock", "malecns", "trained"])
def test_club_chain_is_recorded(controller, synthetic_graph):
    if controller == "mock":
        c = MockBrainController()
    elif controller == "malecns":
        c = MaleCNSController(synthetic_graph)
    else:
        c = TrainedReadoutController(synthetic_graph, _readout(synthetic_graph, {"neural_engine": ENGINE_VERSION}))
    s = RoundSession(c)
    s.new_round(9, start_hole=1)  # a tee shot: the club is the fly's choice
    rec = s.play_shot()
    chain = rec["club_chain"]
    assert chain["club"] == rec["stroke"]["club"]["id"] and chain["forced_club"] is False
    assert chain["club_reach"] == pytest.approx(rec["motor"]["channels"]["club_reach"], abs=1e-6)
    assert club_from_reach(chain["club_reach"]).id == chain["club"]
    if controller == "mock":
        assert chain["readout"] == "mock heuristic" and "dn_all_rate_hz" not in chain
    elif controller == "malecns":
        assert chain["readout"] == "fixed" and chain["dn_all_rate_hz"] >= 0
        r = chain["dn_all_rate_hz"]
        assert chain["club_reach"] == pytest.approx(r / (r + 6.0) if r > 0 else 0.0, abs=1e-5)
    else:
        assert chain["readout"] == "trained" and chain["gate"] == "swing" and chain["club"] == "pw"
        assert chain["club_head_raw"] == pytest.approx(4.0)


# ------------------------------------------------------------------ club_reach -> club


def test_club_reach_mapping_is_monotonic_and_reaches_every_club():
    reaches = np.linspace(0.0, 1.0, 10_001)
    idx = [BAG.index(club_from_reach(float(r))) for r in reaches]
    assert all(b >= a for a, b in zip(idx, idx[1:], strict=False))
    assert sorted(set(idx)) == list(range(len(BAG)))
    widths = np.bincount(idx) / len(reaches)
    assert widths[1:-1] == pytest.approx(1 / 13, abs=1e-3)  # interior slots equally wide
    for club in BAG:
        assert club_from_reach(reach_for(club)) is club
    with pytest.raises(ValueError):
        club_from_reach(1.01)


def test_fixed_readout_club_depends_only_on_dn_rate_and_is_monotonic():
    base = {"steer_L": 0.0, "steer_R": 0.0, "DN_L": 0.0, "DN_R": 0.0}
    clubs = []
    for rate in np.linspace(0.0, 200.0, 2001):
        ch = decode_motor_v2(base | {"DN_all": float(rate)}, dn_spikes=10, dn_early_fraction=0.5)
        clubs.append(BAG.index(club_from_reach(ch["club_reach"])))
    assert all(b >= a for a, b in zip(clubs, clubs[1:], strict=False))
    assert clubs[0] == 0 and clubs[-1] == len(BAG) - 1
