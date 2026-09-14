"""Fly Golf's MaleCNS compiler on small synthetic release files (same schema as the official
flat connectome; the bodies and wiring are invented). The last test compiles the real release
when it is present."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
import pytest

from fly_golf.brain.malecns.graph import load_compiled
from fly_golf.config import load_settings
from fly_golf.data.compiler import (
    COMPILED_FILES,
    COMPILER_VERSION,
    CONTACT_GAIN_MV,
    EdgeList,
    collect_edges,
    compile_release,
    merge_duplicates,
    select_neurons,
    to_csr,
)

LOCK = {
    "dataset": "synthetic",
    "release": "SYNTHETIC RELEASE (not MaleCNS)",
    "license": "test",
    "expected_compiled": {"neurons": 6, "edges": 7},
    "files": {
        n: {"url": "https://example.invalid/" + n, "bytes": 1, "sha256": "0" * 64}
        for n in ("annotations.feather", "neurotransmitters.feather", "edges.feather")
    },
}

# body, superclass, status, type, somaSide, rootSide
BODIES = [
    (500, "cb_intrinsic", "Traced", "CB1", "L", None),
    (100, "descending_neuron", "Traced", "DNa02", "R", None),
    (300, "visual_projection", "Orphan", None, None, "L"),  # untyped orphan with a superclass: kept
    (200, None, "Traced", "X", "L", None),  # no superclass: excluded
    (250, "", "Traced", "Y", "L", None),  # blank superclass: excluded
    (260, "  ", "Traced", "Y2", "L", None),  # whitespace superclass: excluded
    (400, "cb_sensory", "Glia", "G", "R", None),  # glia: excluded even with a superclass
    (700, "vnc_motor", None, "MN1", None, None),  # missing status: kept, side unknown
    (600, "cb_intrinsic", "Unimportant", "CB2", "M", None),
    (800, "ascending_neuron", "Traced", "AN1", "R", "R"),
]
TRANSMITTERS = [(100, "acetylcholine"), (300, "gaba"), (500, "dopamine"), (600, "glutamate"), (400, "gaba")]
# body_pre, body_post, synapse count (release order, spread over several record batches)
EDGES = [
    (500, 100, 3),
    (100, 300, 5),
    (300, 100, 2),
    (100, 100, 1),  # self edge: kept
    (200, 100, 9),  # pre not retained
    (100, 999, 4),  # post absent from the annotations
    (600, 500, 7),
    (400, 100, 2),  # glia pre
    (100, 800, 1),  # weak edge: kept (no threshold)
    (700, 500, 6),
    (888, 777, 2),  # both absent
]


def _write_release(raw, edges=EDGES, bodies=BODIES, batch=3):
    raw.mkdir(parents=True, exist_ok=True)
    ann = pd.DataFrame(bodies, columns=["bodyId", "superclass", "status", "type", "somaSide", "rootSide"])
    ann["bodyId"] = ann["bodyId"].astype("int64")
    ann["instance"] = ann["type"]
    feather.write_feather(ann, raw / "annotations.feather")
    nt = pd.DataFrame(TRANSMITTERS, columns=["body", "consensus_nt"])
    feather.write_feather(nt, raw / "neurotransmitters.feather")
    df = pd.DataFrame(edges, columns=["body_pre", "body_post", "weight"]).astype("int64")
    feather.write_feather(pa.Table.from_pandas(df, preserve_index=False), raw / "edges.feather", chunksize=batch)


@pytest.fixture
def compiled(tmp_path):
    _write_release(tmp_path / "raw")
    manifest = compile_release(tmp_path / "raw", tmp_path / "out", LOCK)
    return load_compiled(tmp_path / "out"), manifest


def _edges(graph):
    pre = np.repeat(np.arange(graph.n), np.diff(graph.ptr))
    ids = graph.ids
    return [
        (int(ids[i]), int(ids[j]), int(c))
        for i, j, c in zip(pre, graph.post, np.load(graph.path / "counts.npy"), strict=True)
    ]


def test_node_rule(compiled):
    graph, manifest = compiled
    assert graph.ids.tolist() == [100, 300, 500, 600, 700, 800]  # sorted body IDs
    assert manifest["neurons"] == 6
    assert manifest["node_accounting"] == {
        "annotation_rows": 10,
        "retained": 6,
        "excluded_no_superclass": 3,
        "excluded_glia": 1,
        "retained_without_transmitter": 2,
    }


def test_edge_rule_and_accounting(compiled):
    graph, manifest = compiled
    assert _edges(graph) == [
        (100, 300, 5),
        (100, 100, 1),
        (100, 800, 1),
        (300, 100, 2),
        (500, 100, 3),
        (600, 500, 7),
        (700, 500, 6),
    ]  # grouped by pre, release order within a group
    assert manifest["edges"] == 7 and manifest["self_edges"] == 1
    assert manifest["synaptic_contacts"] == 25
    assert manifest["edge_accounting"] == {
        "source_rows": 11,
        "source_synaptic_contacts": 42,
        "dropped_endpoint_not_annotated": 2,
        "dropped_endpoint_not_retained": 2,
    }
    assert manifest["matches_expected"] == {"neurons": True, "edges": True, "synaptic_contacts": True}


def test_csr_is_valid(compiled):
    graph, _ = compiled
    ptr, post = np.asarray(graph.ptr), np.asarray(graph.post)
    assert ptr.dtype == np.int64 and post.dtype == np.int32 and graph.weight.dtype == np.float32
    assert ptr[0] == 0 and ptr[-1] == len(post) and np.all(np.diff(ptr) >= 0)
    assert post.min() >= 0 and post.max() < graph.n
    assert np.load(graph.path / "counts.npy").dtype == np.uint32
    assert np.load(graph.path / "ids.npy").dtype == np.int64


def test_weights_follow_sign_and_contact_gain(compiled):
    graph, manifest = compiled
    by_pre = dict(zip(graph.ids.tolist(), graph.neurons["neurotransmitter"].tolist(), strict=True))
    counts = np.load(graph.path / "counts.npy")
    pre = np.repeat(graph.ids, np.diff(graph.ptr))
    sign = {"acetylcholine": 1, "gaba": -1, "glutamate": -1}
    for b, c, w in zip(pre, counts, graph.weight, strict=True):
        expected = sign.get(by_pre[int(b)], 1)  # dopamine and missing -> ambiguous +1
        assert w == np.float32(np.float32(c) * np.float32(expected) * np.float32(CONTACT_GAIN_MV))
    assert manifest["uncertain_sign_neurons"] == 3  # dopamine (500), missing (700, 800)
    assert manifest["sign_reasons"] == {"fast": 3, "modulator_only": 1, "unclear_or_missing": 2}


def test_neuron_metadata(compiled):
    graph, _ = compiled
    t = graph.neurons.set_index("source_id")
    assert list(graph.neurons.columns[:2]) == ["node_index", "source_id"]
    assert graph.neurons["node_index"].tolist() == list(range(6))
    assert t.loc[100, "neurotransmitter"] == "acetylcholine"
    assert pd.isna(t.loc[700, "neurotransmitter"])
    assert t.loc[300, "side"] == "L"  # falls back to rootSide
    assert t.loc[700, "side"] == "unknown"
    assert pd.isna(t.loc[300, "type"])
    assert str(t["type"].dtype) == "string"


def test_deterministic_compile(tmp_path):
    _write_release(tmp_path / "raw")
    a = compile_release(tmp_path / "raw", tmp_path / "a", LOCK)
    b = compile_release(tmp_path / "raw", tmp_path / "b", LOCK)
    volatile = {"compiled_at_utc", "compile_seconds"}
    assert {k: v for k, v in a.items() if k not in volatile} == {k: v for k, v in b.items() if k not in volatile}
    for name in COMPILED_FILES:
        if name != "manifest.json":
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_manifest_contents(compiled):
    _, m = compiled
    for key in (
        "dataset",
        "release",
        "license",
        "node_policy",
        "edge_policy",
        "edge_order",
        "weight_model",
        "sign_model",
        "superclass_counts",
        "source_sha256",
        "arrays_sha256",
    ):
        assert key in m
    assert m["compiler_version"] == COMPILER_VERSION
    assert m["source_sha256"] == {k: "0" * 64 for k in LOCK["files"]}
    assert set(m["arrays_sha256"]) == {"ptr", "post", "weight", "counts", "ids"}


def test_duplicate_pairs_are_summed_in_first_place():
    edges = EdgeList(
        pre=np.array([0, 1, 0, 2, 0], dtype=np.int32),
        post=np.array([1, 2, 1, 0, 2], dtype=np.int32),
        count=np.array([3, 1, 4, 2, 5], dtype=np.uint32),
        accounting={},
    )
    merged, dups = merge_duplicates(edges, 3)
    assert dups == 1
    assert list(zip(merged.pre.tolist(), merged.post.tolist(), merged.count.tolist(), strict=True)) == [
        (0, 1, 7),
        (1, 2, 1),
        (2, 0, 2),
        (0, 2, 5),
    ]
    ptr, post, count, pre = to_csr(merged, 3)
    assert ptr.tolist() == [0, 2, 3, 4] and post.tolist() == [1, 2, 2, 0] and count.tolist() == [7, 5, 1, 2]


def test_duplicates_in_a_release_are_merged(tmp_path):
    _write_release(tmp_path / "raw", edges=[*EDGES, (500, 100, 4)])
    m = compile_release(tmp_path / "raw", tmp_path / "out", LOCK)
    g = load_compiled(tmp_path / "out")
    assert m["duplicate_edge_rows_merged"] == 1 and m["edges"] == 7
    assert (500, 100, 7) in _edges(g)


@pytest.mark.parametrize(
    "bodies",
    [
        [*BODIES, (100, "cb_intrinsic", "Traced", "dup", "L", None)],  # duplicate body ID
    ],
)
def test_duplicate_body_ids_rejected(tmp_path, bodies):
    _write_release(tmp_path / "raw", bodies=bodies)
    with pytest.raises(ValueError, match="duplicate body IDs"):
        compile_release(tmp_path / "raw", tmp_path / "out", LOCK)


def test_bad_synapse_counts_rejected():
    ann = pd.DataFrame(BODIES, columns=["bodyId", "superclass", "status", "type", "somaSide", "rootSide"])
    sel = select_neurons(ann, pd.DataFrame(TRANSMITTERS, columns=["body", "consensus_nt"]))
    for bad in (np.array([0]), np.array([-2]), np.array([1.5])):
        with pytest.raises(ValueError):
            collect_edges([(np.array([100]), np.array([300]), bad)], sel)
    with pytest.raises(ValueError, match="never floats"):
        collect_edges([(np.array([100.0]), np.array([300]), np.array([1]))], sel)


def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="superclass"):
        select_neurons(
            pd.DataFrame({"bodyId": [1], "status": ["Traced"]}),
            pd.DataFrame(TRANSMITTERS, columns=["body", "consensus_nt"]),
        )


def test_interrupted_compile_never_looks_complete(tmp_path, monkeypatch):
    _write_release(tmp_path / "raw")
    compile_release(tmp_path / "raw", tmp_path / "out", LOCK)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("pyarrow.feather.write_feather", boom)
    with pytest.raises(RuntimeError):
        compile_release(tmp_path / "raw", tmp_path / "out", LOCK)
    assert not (tmp_path / "out" / "manifest.json").exists()


# ---------------------------------------------------------------- the real release


@pytest.mark.integration
def test_real_release_compiles_to_the_locked_counts(tmp_path):
    s = load_settings()
    if not all((s.raw_dir / n).exists() for n in LOCK["files"]):
        pytest.skip("MaleCNS source files not present (run `make data`)")
    lock = json.loads(s.lock_path.read_text())
    m = compile_release(s.raw_dir, tmp_path / "out", lock)
    assert all(m["matches_expected"].values()), m["matches_expected"]
    assert m["neurons"] == lock["expected_compiled"]["neurons"]
    assert m["edges"] == lock["expected_compiled"]["edges"]
    # the counts come from the rules, not from the lock: re-derive the two headline numbers
    ann = feather.read_table(s.raw_dir / "annotations.feather", columns=["superclass", "status"]).to_pandas()
    sc = ann["superclass"].astype("string")
    assert m["neurons"] == int((sc.notna() & sc.str.strip().ne("") & ann["status"].ne("Glia")).sum())
    installed = s.compiled_dir / "manifest.json"
    if installed.exists() and json.loads(installed.read_text()).get("arrays_sha256"):
        assert json.loads(installed.read_text())["arrays_sha256"] == m["arrays_sha256"]
