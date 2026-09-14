"""Build the brain soma map that the web app's "Brain firing" view draws recorded activity on.

Output: apps/web/public/anatomy/malecns-brain-somata.json (tens of kB). It contains:

* a density map of MaleCNS v1.0 cell-body (soma) positions in the brain, seen from behind
  (the fly's left on the left), binned into square cells of 1,000 voxels;
* for each Fly Golf sensory/motor population, which map cells hold its somata (so the app can
  light a population where its cell bodies really are), and how many of its neurons have no
  soma in the imaged CNS (their cell bodies sit in the antennae, eyes or legs);
* the soma position of every neuron of the named readout types (NAMED_READOUT_TYPES).

It contains no activity: the app lights these cells with each shot's recorded population rates.
The populations are resolved with the simulator's own `resolve_populations`, so the map matches
the recorded populations exactly. The output is deterministic (no timestamps).

Needs the downloaded and compiled connectome (`make data`). Run from the repository root:

    uv --directory services/sim run python scripts/build_soma_map.py
    uv --directory services/sim run python scripts/build_soma_map.py --data-dir /path/to/data

MaleCNS v1.0 (c) the MaleCNS collaboration, CC BY 4.0 (THIRD_PARTY_NOTICES.md). Binning and
projecting soma positions are Fly Golf's transformations; the dataset creators have not
validated them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

from fly_golf.brain.malecns.populations import (
    MALECNS_MOTOR_MAPPING_VERSION_V2,
    MALECNS_SENSORY_MAPPING_VERSION_V2,
    NAMED_READOUT_TYPES,
    resolve_populations,
    spec_by_name,
)

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "apps" / "web" / "public" / "anatomy" / "malecns-brain-somata.json"
CELL = 1000  # voxels per map cell
FORMAT = "fly-golf-soma-map"
VERSION = 1

ATTRIBUTION = (
    "Soma positions: MaleCNS v1.0, (c) the MaleCNS collaboration (FlyEM/HHMI Janelia, University of "
    "Cambridge, MRC LMB, Google Research), CC BY 4.0, https://doi.org/10.1016/j.cell.2026.08.015. "
    "Binned and projected by Fly Golf (services/sim/scripts/build_soma_map.py); the dataset creators "
    "have not validated this transformation."
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def soma_positions(annotations: Path, body_ids: np.ndarray) -> np.ndarray:
    """(n, 3) soma positions in voxels for the compiled neurons, NaN where there is none."""
    table = feather.read_table(annotations, columns=["bodyId", "somaLocation"]).to_pandas()
    table = table.drop_duplicates("bodyId").set_index("bodyId")["somaLocation"]
    locs = table.reindex(body_ids).to_numpy()
    xyz = np.full((len(body_ids), 3), np.nan)
    for i, v in enumerate(locs):
        if v is not None and not isinstance(v, float) and len(v) == 3:
            xyz[i] = v
    return xyz


def neck_z(z: np.ndarray) -> float:
    """The z (voxels) of the neck: the sparsest 1k-voxel slab between the brain and the nerve cord."""
    edges = np.arange(30_000, 70_001, 1_000)
    counts, _ = np.histogram(z, bins=edges)
    smooth = np.convolve(counts, np.ones(3) / 3, mode="same")
    i = int(np.argmin(smooth[1:-1])) + 1
    return float(edges[i] + 500)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=REPO / "data", help="the data/ directory of `make data`")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    raw = args.data_dir / "raw" / "malecns_v1" / "annotations.feather"
    compiled = args.data_dir / "compiled" / "malecns_v1"
    lock = json.loads((REPO / "data" / "malecns_v1.lock.json").read_text())
    expected = lock["files"]["annotations.feather"]["sha256"]
    actual = sha256(raw)
    if actual != expected:
        raise SystemExit(f"{raw} does not match the source lock (sha256 {actual}, expected {expected})")
    manifest = json.loads((compiled / "manifest.json").read_text())

    neurons = feather.read_table(compiled / "neurons.feather").to_pandas()
    xyz = soma_positions(raw, neurons["source_id"].to_numpy())
    has_soma = ~np.isnan(xyz[:, 0])
    z_neck = neck_z(xyz[has_soma, 2])
    in_brain = has_soma & (xyz[:, 2] < z_neck)
    in_vnc = has_soma & (xyz[:, 2] >= z_neck)

    # Posterior view: the fly's left (high x in this volume, e.g. LC10_L) on the left of the map,
    # dorsal at the top. Robust bounds so a few stray somata do not stretch the map.
    bx, by = xyz[in_brain, 0], xyz[in_brain, 1]
    x_lo, x_hi = np.percentile(bx, [0.02, 99.98])
    y_lo, y_hi = np.percentile(by, [0.02, 99.98])
    cols = int((x_hi - x_lo) // CELL) + 1
    rows = int((y_hi - y_lo) // CELL) + 1

    def to_map(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        col = np.clip((x_hi - p[:, 0]) / CELL, 0, cols - 1e-6)
        row = np.clip((p[:, 1] - y_lo) / CELL, 0, rows - 1e-6)
        return col, row

    col, row = to_map(xyz[in_brain])
    flat = row.astype(int) * cols + col.astype(int)
    counts = np.bincount(flat, minlength=rows * cols)

    brain_index = np.flatnonzero(in_brain)
    flat_of = np.full(len(neurons), -1, dtype=np.int64)
    flat_of[brain_index] = flat

    populations = {}
    specs = spec_by_name()
    for name, idx in resolve_populations(neurons).items():
        idx = np.asarray(idx, dtype=np.int64)
        cells = flat_of[idx]
        cells = cells[cells >= 0]
        uniq, n = np.unique(cells, return_counts=True)
        populations[name] = {
            "role": specs[name].role,
            "neurons": int(len(idx)),
            "brain": int(len(cells)),
            "vnc": int(in_vnc[idx].sum()),
            "outside": int((~has_soma[idx]).sum()),
            # flat cell index, somata in that cell, ...
            "cells": [int(v) for pair in zip(uniq, n, strict=True) for v in pair],
        }

    types = neurons["type"].astype(object).fillna("").astype(str).to_numpy()
    named_idx = np.flatnonzero(np.isin(types, NAMED_READOUT_TYPES))
    named = {}
    for i in named_idx:
        if not in_brain[i]:
            continue
        c, r = to_map(xyz[i : i + 1])
        named[str(int(neurons["source_id"].iat[i]))] = [round(float(c[0]), 2), round(float(r[0]), 2)]

    out = {
        "format": FORMAT,
        "version": VERSION,
        "attribution": ATTRIBUTION,
        "generated_by": "services/sim/scripts/build_soma_map.py",
        "source": {
            "release": lock["release"],
            "license": lock["license"],
            "annotations_sha256": actual,
            "compiler_version": manifest.get("compiler_version"),
            "neurons": int(len(neurons)),
            "sensory_mapping": MALECNS_SENSORY_MAPPING_VERSION_V2,
            "motor_mapping": MALECNS_MOTOR_MAPPING_VERSION_V2,
        },
        "view": (
            "Brain somata (z below the neck at "
            f"{int(z_neck)} voxels), projected along the anterior-posterior axis and seen from behind: "
            "the fly's left is on the left, dorsal at the top."
        ),
        "cell_voxels": CELL,
        "cols": cols,
        "rows": rows,
        "somata": {
            "brain": int(in_brain.sum()),
            "vnc": int(in_vnc.sum()),
            "none": int((~has_soma).sum()),
        },
        "counts": [int(v) for v in counts],
        "populations": populations,
        "named_types": list(NAMED_READOUT_TYPES),
        "named": named,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    size = args.out.stat().st_size
    print(f"neck at z = {z_neck:.0f} voxels; map {cols} x {rows} cells")
    print(f"somata: brain {out['somata']}; named placed {len(named)} of {len(named_idx)}")
    for name, p in populations.items():
        print(f"  {name:12s} n={p['neurons']:5d} brain={p['brain']:5d} vnc={p['vnc']:4d} outside={p['outside']:4d}")
    print(f"wrote {args.out} ({size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
