"""Shared fixtures: a tiny synthetic 'connectome' with the same file layout and
neuron annotations as the compiled MaleCNS graph. Its wiring is invented for
software testing only and says nothing about the real fly."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fly_golf.brain.malecns.graph import load_compiled, save_compiled


def _neuron_table(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "node_index": np.arange(len(rows), dtype=np.int32),
            "source_id": np.arange(1000, 1000 + len(rows), dtype=np.int64),
            "type": pd.array([r[0] for r in rows], dtype="string"),
            "superclass": pd.array([r[1] for r in rows], dtype="string"),
            "side": pd.array([r[2] for r in rows], dtype="string"),
            "subclass": pd.array([r[3] for r in rows], dtype="string"),
        }
    )


def build_synthetic_graph(tmp_path):
    rows = []

    def add(type_, superclass, side, count, subclass=""):
        start = len(rows)
        rows.extend([(type_, superclass, side, subclass)] * count)
        return list(range(start, start + count))

    lc_l = add("LC10a", "visual_projection", "L", 6)
    lc_r = add("LC10a", "visual_projection", "R", 6)
    joc_l = add("JO-CM", "cb_sensory", "L", 3)
    joc_r = add("JO-CM", "cb_sensory", "R", 3)
    joe_l = add("JO-EV1", "cb_sensory", "L", 3)
    joe_r = add("JO-EV1", "cb_sensory", "R", 3)
    dna_l = add("DNa02", "descending_neuron", "L", 1)
    dna_r = add("DNa02", "descending_neuron", "R", 1)
    dn_l = add("DNg10", "descending_neuron", "L", 4)
    dn_r = add("DNg10", "descending_neuron", "R", 4)
    dnp_l = add("DNp09", "descending_neuron", "L", 2)
    dnp_r = add("DNp09", "descending_neuron", "R", 2)
    inter = add("CB0001", "cb_intrinsic", "M", 4)
    lc15 = add("LC15", "visual_projection", "L", 3) + add("LC15", "visual_projection", "R", 3)
    bristle = add("LgBr1", "vnc_sensory", "L", 2, "leg bristle") + add("LgBr1", "vnc_sensory", "R", 2, "leg bristle")
    pol = add("R7d", "ol_sensory", "L", 2) + add("R8d", "ol_sensory", "R", 2)

    edges = []

    def connect(src, dst, w):
        for i in src:
            for j in dst:
                edges.append((i, j, w))

    # Invented wiring: ipsilateral LC10 -> steering DN and DN pool; JO -> interneurons.
    connect(lc_l, dna_l + dn_l, 12.0)
    connect(lc_r, dna_r + dn_r, 12.0)
    connect(joc_l + joe_l, inter[:2], 6.0)
    connect(joc_r + joe_r, inter[2:], 6.0)
    connect(inter, dn_l + dn_r, 1.0)
    connect(dna_l, dna_r, -20.0)  # mutual inhibition
    connect(dna_r, dna_l, -20.0)
    # v0.2 inputs: far-target cue and ground texture reach the DN pool; water glint inhibits it.
    connect(lc15, dnp_l + dnp_r, 9.0)
    connect(bristle, inter, 5.0)
    connect(inter, dnp_l + dnp_r, 2.0)
    connect(pol, dn_l + dn_r, -3.0)

    n = len(rows)
    edges.sort()
    pre = np.array([e[0] for e in edges], dtype=np.int64)
    post = np.array([e[1] for e in edges], dtype=np.int32)
    weight = np.array([e[2] for e in edges], dtype=np.float32)
    ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(pre, minlength=n), out=ptr[1:])
    neurons = _neuron_table(rows)
    manifest = {"release": "SYNTHETIC TEST GRAPH (not MaleCNS)", "neurons": n, "edges": len(post)}
    d = tmp_path / "compiled"
    save_compiled(d, ptr, post, weight, neurons, manifest)
    return d


@pytest.fixture
def synthetic_graph(tmp_path):
    return load_compiled(build_synthetic_graph(tmp_path))


@pytest.fixture
def synthetic_graph_dir(tmp_path):
    return build_synthetic_graph(tmp_path)
