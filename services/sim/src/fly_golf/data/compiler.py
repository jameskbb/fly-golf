"""Fly Golf's MaleCNS v1.0 compiler: the official flat-connectome files -> a CSR graph.

Written for Fly Golf against the official release schema (docs/DATA.md):

    body annotations    bodyId, superclass, status, type, instance, somaSide, rootSide, ...
    neurotransmitters   body, consensus_nt, ...
    connectome weights  body_pre, body_post, weight (synapse count, confidence >= 0.5)

Fly Golf's modelling decisions (docs/PROVENANCE.md explains why):

* NODE RULE: a body is a neuron of the model if the release assigns it a superclass and its
  status is not "Glia". Nothing else is required (untraced, untyped and orphan bodies with a
  superclass stay). In v1.0 no Glia body has a superclass, so the second clause is a guard.
* EDGE RULE: every released edge whose two endpoints are retained neurons is kept, with no
  synapse-count threshold; self edges are kept; duplicate (pre, post) rows would be merged by
  summing their counts (v1.0 has none).
* WEIGHT: synapse count x sign of the presynaptic neuron's transmitter (transmitters.py) x
  0.275 mV, the per-synapse weight of Shiu et al. (2024).
* ORDER: neurons by ascending body ID; edges grouped by presynaptic neuron, keeping the order
  of the release file within each group. Fly Golf's engine does not depend on edge order; the
  legacy engine does, and this order keeps its old records reproducible.

Outputs, in data/compiled/malecns_v1/ (git-ignored):
    ptr.npy (int64, n + 1)   post.npy (int32)   weight.npy (float32)   counts.npy (uint32)
    ids.npy (int64)          neurons.feather     manifest.json
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..brain.malecns.transmitters import SIGN_MODEL, sign_reasons, transmitter_signs

COMPILER_VERSION = "fly-golf-compile-v2"
CONTACT_GAIN_MV = 0.275
NODE_RULE = "assigned superclass and status != 'Glia'; no restriction to traced or typed bodies"
EDGE_RULE = "every released edge between retained neurons; no count threshold; self edges kept; duplicates summed"
EDGE_ORDER = "grouped by presynaptic neuron (ascending body ID); release-file order within a group"
WEIGHT_MODEL = f"synapse_count x transmitter_sign x {CONTACT_GAIN_MV} mV"

ANNOTATION_ID, NT_ID, NT_LABEL = "bodyId", "body", "consensus_nt"
EDGE_PRE, EDGE_POST, EDGE_COUNT = "body_pre", "body_post", "weight"
NEURON_COLUMNS = [
    "type",
    "instance",
    "superclass",
    "class",
    "subclass",
    "somaSide",
    "rootSide",
    "status",
    "statusLabel",
    "entryNerve",
    "exitNerve",
    "somaNeuromere",
    "receptorType",
    "flywireType",
    "assignedOlHex1",
    "assignedOlHex2",
]
ARRAY_FILES = ["ptr.npy", "post.npy", "weight.npy", "counts.npy", "ids.npy"]
COMPILED_FILES = [*ARRAY_FILES, "neurons.feather", "manifest.json"]


# ------------------------------------------------------------------------------ neurons
@dataclass
class NeuronSelection:
    table: pd.DataFrame  # one row per retained neuron, in node-index order
    ids: np.ndarray  # retained body IDs, ascending (int64)
    annotated_ids: np.ndarray  # every body ID in the annotation table, ascending
    counts: dict = field(default_factory=dict)


def _is_text(series: pd.Series) -> bool:
    return (
        series.dtype == object
        or pd.api.types.is_string_dtype(series.dtype)
        or isinstance(series.dtype, pd.CategoricalDtype)
    )


def _text(series: pd.Series) -> pd.Series:
    """Nullable string column (missing -> <NA>), independent of how the file stored it."""
    return series.astype(object).where(series.notna(), None).astype(pd.StringDtype())


def _body_ids(values, what: str) -> np.ndarray:
    arr = np.asarray(values)
    if arr.dtype.kind not in "iu":
        raise ValueError(f"{what} must be integers (got {arr.dtype}); body IDs are never floats")
    if len(arr) and arr.min() < 0:
        raise ValueError(f"{what} cannot be negative")
    return arr.astype(np.int64)


def select_neurons(annotations: pd.DataFrame, transmitters: pd.DataFrame) -> NeuronSelection:
    """Apply the node rule; attach each neuron's transmitter label and a single `side`."""
    for col in (ANNOTATION_ID, "superclass", "status"):
        if col not in annotations.columns:
            raise ValueError(f"annotation table has no {col!r} column")
    for col in (NT_ID, NT_LABEL):
        if col not in transmitters.columns:
            raise ValueError(f"neurotransmitter table has no {col!r} column")
    body = _body_ids(annotations[ANNOTATION_ID], "annotation body IDs")
    if len(np.unique(body)) != len(body):
        raise ValueError("duplicate body IDs in the annotation table")
    nt_body = _body_ids(transmitters[NT_ID], "neurotransmitter body IDs")
    if len(np.unique(nt_body)) != len(nt_body):
        raise ValueError("duplicate body IDs in the neurotransmitter table")

    superclass = annotations["superclass"].astype(pd.StringDtype())
    assigned = (superclass.notna() & superclass.str.strip().ne("")).fillna(False).to_numpy(dtype=bool)
    glia = annotations["status"].astype(pd.StringDtype()).eq("Glia").fillna(False).to_numpy(dtype=bool)
    keep = assigned & ~glia
    order = np.argsort(body[keep], kind="stable")
    kept = annotations.loc[keep].iloc[order].reset_index(drop=True)
    ids = body[keep][order]

    table = pd.DataFrame({"node_index": np.arange(len(kept), dtype=np.int32), "source_id": ids})
    for col in NEURON_COLUMNS:
        if col in kept.columns:
            table[col] = _text(kept[col]) if _is_text(kept[col]) else kept[col].to_numpy()
    label = pd.Series(transmitters[NT_LABEL].to_numpy(), index=nt_body)
    table["neurotransmitter"] = _text(pd.Series(ids).map(label))
    side = pd.Series(pd.NA, index=table.index, dtype=pd.StringDtype())
    for col in ("somaSide", "rootSide"):
        if col in table.columns:
            side = side.fillna(table[col].astype(pd.StringDtype()))
    table["side"] = side.fillna("unknown")

    counts = {
        "annotation_rows": int(len(annotations)),
        "retained": int(keep.sum()),
        "excluded_no_superclass": int((~assigned).sum()),
        "excluded_glia": int((assigned & glia).sum()),
        "retained_without_transmitter": int(table["neurotransmitter"].isna().sum()),
    }
    return NeuronSelection(table=table, ids=ids, annotated_ids=np.sort(body), counts=counts)


# -------------------------------------------------------------------------------- edges
def _position(sorted_ids: np.ndarray, bodies: np.ndarray) -> np.ndarray:
    """Index of each body in `sorted_ids`, or -1 where it is not there."""
    if not len(sorted_ids):
        return np.full(len(bodies), -1, dtype=np.int64)
    at = np.searchsorted(sorted_ids, bodies)
    clipped = np.minimum(at, len(sorted_ids) - 1)
    return np.where(sorted_ids[clipped] == bodies, clipped, -1)


@dataclass
class EdgeList:
    pre: np.ndarray  # node index (int32), release order
    post: np.ndarray  # node index (int32)
    count: np.ndarray  # synapse count (uint32)
    accounting: dict


def collect_edges(batches: Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]], neurons: NeuronSelection) -> EdgeList:
    """Apply the edge rule to (body_pre, body_post, synapse count) batches, accounting for
    every row that is not kept."""
    pres, posts, counts = [], [], []
    acc = {
        "source_rows": 0,
        "source_synaptic_contacts": 0,
        "dropped_endpoint_not_annotated": 0,
        "dropped_endpoint_not_retained": 0,
    }
    for body_pre, body_post, count in batches:
        body_pre = _body_ids(body_pre, "edge body_pre")
        body_post = _body_ids(body_post, "edge body_post")
        count = np.asarray(count)
        if count.dtype.kind not in "iu":
            raise ValueError(f"synapse counts must be integers (got {count.dtype})")
        if len(count) and (count.min() < 1 or count.max() > np.iinfo(np.uint32).max):
            raise ValueError("synapse counts must be positive and fit in uint32")
        i = _position(neurons.ids, body_pre)
        j = _position(neurons.ids, body_post)
        kept = (i >= 0) & (j >= 0)
        annotated = (_position(neurons.annotated_ids, body_pre) >= 0) & (
            _position(neurons.annotated_ids, body_post) >= 0
        )
        acc["source_rows"] += len(count)
        acc["source_synaptic_contacts"] += int(count.sum(dtype=np.int64))
        acc["dropped_endpoint_not_annotated"] += int((~annotated).sum())
        acc["dropped_endpoint_not_retained"] += int((annotated & ~kept).sum())
        pres.append(i[kept].astype(np.int32))
        posts.append(j[kept].astype(np.int32))
        counts.append(count[kept].astype(np.uint32))
    cat = lambda parts, dtype: np.concatenate(parts) if parts else np.zeros(0, dtype=dtype)  # noqa: E731
    return EdgeList(cat(pres, np.int32), cat(posts, np.int32), cat(counts, np.uint32), acc)


def merge_duplicates(edges: EdgeList, n: int) -> tuple[EdgeList, int]:
    """Sum the counts of repeated (pre, post) rows into the first occurrence."""
    key = edges.pre.astype(np.int64) * n + edges.post.astype(np.int64)
    by_key = np.argsort(key, kind="stable")
    sorted_key = key[by_key]
    starts = np.ones(len(key), dtype=bool)
    starts[1:] = sorted_key[1:] != sorted_key[:-1]
    duplicates = int(len(key) - starts.sum())
    if not duplicates:
        return edges, 0
    group = np.cumsum(starts) - 1
    summed = np.bincount(group, weights=edges.count[by_key].astype(np.float64)).astype(np.uint64)
    if summed.max() > np.iinfo(np.uint32).max:
        raise ValueError("merged synapse count overflows uint32")
    first = by_key[starts]  # each pair's first row, in key order
    keep_order = np.argsort(first, kind="stable")
    rows = first[keep_order]
    merged = EdgeList(edges.pre[rows], edges.post[rows], summed[keep_order].astype(np.uint32), edges.accounting)
    return merged, duplicates


def to_csr(edges: EdgeList, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(ptr, post, count, pre) with edges grouped by presynaptic neuron, release order kept."""
    order = np.argsort(edges.pre, kind="stable")
    ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(edges.pre, minlength=n), out=ptr[1:])
    return ptr, edges.post[order], edges.count[order], edges.pre[order]


def synaptic_weights(count: np.ndarray, pre: np.ndarray, signs: np.ndarray) -> np.ndarray:
    """Weight (mV) per edge: count x sign(pre) x 0.275 mV, in float32 arithmetic (the compiled
    format stores float32, and this keeps weight.npy bit-identical across compiler versions)."""
    return (count.astype(np.float32) * signs[pre].astype(np.float32) * np.float32(CONTACT_GAIN_MV)).astype(np.float32)


# ------------------------------------------------------------------------------ compile
def read_edge_batches(path: Path) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Stream (body_pre, body_post, weight) record batches from the edge feather file."""
    import pyarrow as pa
    import pyarrow.ipc as ipc

    reader = ipc.open_file(pa.memory_map(str(path), "r"))
    names = reader.schema.names
    for col in (EDGE_PRE, EDGE_POST, EDGE_COUNT):
        if col not in names:
            raise ValueError(f"edge table has no {col!r} column")
    for b in range(reader.num_record_batches):
        batch = reader.get_batch(b)
        yield tuple(batch.column(names.index(c)).to_numpy() for c in (EDGE_PRE, EDGE_POST, EDGE_COUNT))


def arrays_sha256(arrays: dict[str, np.ndarray]) -> dict[str, str]:
    return {name: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest() for name, a in arrays.items()}


def compile_release(
    raw_dir: Path,
    out_dir: Path,
    lock: dict,
    log: Callable[[str], None] = lambda _msg: None,
) -> dict:
    """Compile the three locked source files in `raw_dir` into `out_dir`. Returns the manifest."""
    import pyarrow.feather as feather

    t0 = time.time()
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    log("reading annotations + neurotransmitters ...")
    annotations = feather.read_table(raw_dir / "annotations.feather").to_pandas()
    transmitters = feather.read_table(raw_dir / "neurotransmitters.feather").to_pandas()
    neurons = select_neurons(annotations, transmitters)
    n = len(neurons.ids)
    log(f"retained {n:,} neurons of {len(annotations):,} annotation rows")

    log("collecting edges (streaming record batches) ...")
    edges = collect_edges(read_edge_batches(raw_dir / "edges.feather"), neurons)
    edges, duplicates = merge_duplicates(edges, n)
    ptr, post, count, pre = to_csr(edges, n)
    labels = neurons.table["neurotransmitter"]
    signs, ambiguous = transmitter_signs(labels)
    weight = synaptic_weights(count, pre, signs)
    self_edges = int(np.count_nonzero(pre == post))
    acc = edges.accounting
    log(f"retained {len(post):,} of {acc['source_rows']:,} edge rows")
    del pre, edges

    arrays = {"ptr": ptr, "post": post, "weight": weight, "counts": count, "ids": neurons.ids}
    write_compiled(out_dir, arrays, neurons.table)
    contacts = int(count.sum(dtype=np.uint64))
    produced = {"neurons": int(n), "edges": int(len(post)), "synaptic_contacts": contacts}
    expected = lock.get("expected_compiled", {})
    manifest = {
        "dataset": lock["dataset"],
        "release": lock["release"],
        "license": lock["license"],
        "compiler_version": COMPILER_VERSION,
        "compiled_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **produced,
        "source_annotation_rows": neurons.counts["annotation_rows"],
        "source_edge_rows": acc["source_rows"],
        "source_synaptic_contacts": acc["source_synaptic_contacts"],
        "self_edges": self_edges,
        "duplicate_edge_rows_merged": duplicates,
        "uncertain_sign_neurons": int(ambiguous.sum()),
        "sign_reasons": sign_reasons(labels),
        "node_accounting": neurons.counts,
        "edge_accounting": acc,
        "matches_expected": {k: expected.get(k) is None or expected[k] == v for k, v in produced.items()},
        "node_policy": NODE_RULE,
        "edge_policy": EDGE_RULE,
        "edge_order": EDGE_ORDER,
        "weight_model": WEIGHT_MODEL,
        "sign_model": SIGN_MODEL,
        "superclass_counts": neurons.table["superclass"].value_counts().to_dict(),
        "source_sha256": {k: v["sha256"] for k, v in lock["files"].items()},
        "arrays_sha256": arrays_sha256(arrays),
        "compile_seconds": round(time.time() - t0, 1),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"compiled {n:,} neurons / {len(post):,} edges in {manifest['compile_seconds']} s -> {out_dir}")
    return manifest


def write_compiled(out_dir: Path, arrays: dict[str, np.ndarray], table: pd.DataFrame) -> None:
    """Write each file beside its final name and move it into place; the manifest comes last."""
    import pyarrow.feather as feather

    out_dir.mkdir(parents=True, exist_ok=True)
    stale = out_dir / "manifest.json"
    if stale.exists():
        stale.unlink()  # an interrupted rewrite must never look complete
    for name, arr in arrays.items():
        tmp = out_dir / f"{name}.npy.partial"
        with tmp.open("wb") as fh:
            np.save(fh, arr)
        tmp.replace(out_dir / f"{name}.npy")
    tmp = out_dir / "neurons.feather.partial"
    feather.write_feather(table, tmp)
    tmp.replace(out_dir / "neurons.feather")
