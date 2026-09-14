"""Load (and, for tests, save) the compiled simulation-ready graph."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class CompiledGraph:
    ptr: np.ndarray
    post: np.ndarray
    weight: np.ndarray
    ids: np.ndarray
    neurons: pd.DataFrame
    manifest: dict
    path: Path | None = None

    @property
    def n(self) -> int:
        return len(self.ptr) - 1

    @property
    def edges(self) -> int:
        return len(self.post)


def load_compiled(directory: Path, mmap: bool = True) -> CompiledGraph:
    import pyarrow.feather as feather

    directory = Path(directory)
    mode = "r" if mmap else None
    manifest = json.loads((directory / "manifest.json").read_text())
    ptr = np.load(directory / "ptr.npy", mmap_mode=mode)
    post = np.load(directory / "post.npy", mmap_mode=mode)
    weight = np.load(directory / "weight.npy", mmap_mode=mode)
    ids = np.load(directory / "ids.npy", mmap_mode=mode)
    neurons = feather.read_table(directory / "neurons.feather").to_pandas()
    if len(neurons) != len(ptr) - 1 or len(ids) != len(neurons):
        raise ValueError("compiled graph files are inconsistent (neuron counts differ)")
    return CompiledGraph(ptr, post, weight, ids, neurons, manifest, directory)


def save_compiled(
    directory: Path,
    ptr: np.ndarray,
    post: np.ndarray,
    weight: np.ndarray,
    neurons: pd.DataFrame,
    manifest: dict,
) -> None:
    """Write a compiled graph in the same layout as `fly-golf-data prepare` (used for fixtures)."""
    import pyarrow.feather as feather

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "ptr.npy", np.asarray(ptr, dtype=np.int64))
    np.save(directory / "post.npy", np.asarray(post, dtype=np.int32))
    np.save(directory / "weight.npy", np.asarray(weight, dtype=np.float32))
    np.save(directory / "counts.npy", np.abs(np.asarray(weight, dtype=np.float32) / 0.275).astype(np.uint32))
    np.save(directory / "ids.npy", neurons["source_id"].to_numpy(dtype=np.int64))
    feather.write_feather(neurons, directory / "neurons.feather")
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
