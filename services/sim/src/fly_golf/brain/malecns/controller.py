"""MaleCNSController: a BrainController driven by simulated neural dynamics
operating over the reconstructed MaleCNS v1.0 connectome.

Per stroke (decision window, default 400 ms of simulated neural time):
  1. reset neural state to rest (every stroke starts from the same state);
  2. proxy sensory channels -> constant drive on documented sensory populations;
  3. run the LIF engine over the full graph (all retained neurons and edges);
  4. read spike counts of documented output populations after READOUT_START_MS;
  5. convert population statistics to the bounded motor channels.

The mapping version follows the sensory frame: a v0.1 frame (9 channels, recorded putting
runs) uses the v0.1 injection and 7-channel readout exactly as before; a v0.2 frame (the
course) adds three injected populations and the club_reach channel.

No golf state, reward, cup position or physics ever reaches this class; it sees
only the `SensoryFrame`. The motor decoder downstream is shared with the mock.
"""

from __future__ import annotations

import math

import numpy as np

from ..interfaces import ControllerInfo, ControllerKind, MotorCommand, NeuralSummary, SensoryFrame
from .engine import ENGINE_VERSION, make_engine
from .graph import CompiledGraph
from .populations import (
    BIN_MS,
    MALECNS_MOTOR_MAPPING_VERSION,
    MALECNS_MOTOR_MAPPING_VERSION_V2,
    MALECNS_SENSORY_MAPPING_VERSION,
    MALECNS_SENSORY_MAPPING_VERSION_V2,
    NAMED_READOUT_TYPES,
    REACH_HALF_HZ,
    READOUT_START_MS,
    SENSORY_POPULATIONS_V2,
    decode_motor,
    decode_motor_v2,
    resolve_populations,
    sensory_drive,
    sensory_drive_v2,
    spec_by_name,
)

# Trained-readout feature spaces: DN-type mean rates, or DN-type x soma-side mean rates.
FEATURE_SPACE = "dn-type"
FEATURE_SPACE_SIDE = "dn-type-side"
FEATURE_SPACES = (FEATURE_SPACE, FEATURE_SPACE_SIDE)


class MaleCNSController:
    def __init__(self, graph: CompiledGraph, readout_start_ms: float = READOUT_START_MS, engine: str = ENGINE_VERSION):
        self.graph = graph
        self.engine_version = engine
        self.engine = make_engine(engine, graph.ptr, graph.post, graph.weight)
        self.populations = resolve_populations(graph.neurons)
        # v0.1 populations are required (recorded runs must replay); the v0.2 additions are only
        # required once a v0.2 frame arrives, so an older compiled graph can still replay v0.1.
        empty = [k for k, v in self.populations.items() if len(v) == 0]
        v2_only = {s.name for s in SENSORY_POPULATIONS_V2}
        if [k for k in empty if k not in v2_only]:
            raise ValueError(f"populations resolved to zero neurons: {empty}")
        self._missing_v2 = [k for k in empty if k in v2_only]
        self.readout_start_ms = readout_start_ms
        types = graph.neurons["type"].astype(object).fillna("").astype(str).to_numpy()
        sides = graph.neurons["side"].astype(object).fillna("?").astype(str).to_numpy()
        self.named = [
            {"index": int(i), "type": types[i], "side": sides[i], "id": str(int(graph.ids[i]))}
            for i in np.flatnonzero(np.isin(types, NAMED_READOUT_TYPES))
        ]
        # Descending-neuron types (the brain's output to the body): the feature space for
        # trained readouts. One feature per DN type = mean rate over its neurons.
        dn = self.populations["DN_all"]
        dn_types = types[dn]
        self.feature_names, self._dn_group = np.unique(dn_types, return_inverse=True)
        self._dn_group_size = np.bincount(self._dn_group).astype(np.float64)
        # The same DN types split by soma side ("DNa01|L"): a type's mean merges its left and
        # right neurons, which cancels exactly the asymmetry that steering is read from.
        self.feature_names_side, self._dn_group_side = np.unique(
            np.char.add(np.char.add(dn_types.astype(str), "|"), sides[dn].astype(str)), return_inverse=True
        )
        self._dn_group_side_size = np.bincount(self._dn_group_side).astype(np.float64)
        self.info = ControllerInfo(
            id="malecns",
            kind=ControllerKind.MALECNS,
            label="MaleCNS LIVE",
            is_mock=False,
            description=(
                "Simulated LIF dynamics over every retained MaleCNS v1.0 neuron and edge. Proxy "
                "sensory injection and engineered motor readout (see docs/SENSORY_MAPPING.md, "
                "docs/MOTOR_MAPPING.md)."
            ),
            neuron_count=graph.n,
            edge_count=graph.edges,
            connectome=graph.manifest.get("release", "MaleCNS v1.0"),
            model=engine,
            config={
                "sensory_mapping": MALECNS_SENSORY_MAPPING_VERSION_V2,
                "motor_mapping": MALECNS_MOTOR_MAPPING_VERSION_V2,
                "legacy_mappings": [MALECNS_SENSORY_MAPPING_VERSION, MALECNS_MOTOR_MAPPING_VERSION],
                "engine": engine,
                "readout_start_ms": readout_start_ms,
                "bin_ms": BIN_MS,
                "population_sizes": {k: int(len(v)) for k, v in self.populations.items()},
            },
        )
        self._frame: SensoryFrame | None = None
        self._command: MotorCommand | None = None
        self._trace: dict | None = None
        self._features: np.ndarray | None = None
        self._base_channels: dict[str, float] | None = None
        self._rates: dict[str, float] = {}

    def reset(self, seed: int) -> None:
        # The LIF model is deterministic; the seed is recorded but unused.
        self.engine.reset()
        self._frame = None
        self._command = None
        self._trace = None
        self._features = None
        self._base_channels = None

    def observe(self, frame: SensoryFrame) -> None:
        if not isinstance(frame, SensoryFrame):
            raise ValueError("observe() requires a SensoryFrame")
        if not frame.is_legacy and self._missing_v2:
            raise ValueError(f"v0.2 frames need populations missing from this graph: {self._missing_v2}")
        self._frame = frame
        drive_fn = sensory_drive if frame.is_legacy else sensory_drive_v2
        self._drive_by_pop = drive_fn(dict(frame.channels))
        drive = np.zeros(self.engine.n, dtype=np.float64)
        for name, value in self._drive_by_pop.items():
            drive[self.populations[name]] = value
        self.engine.set_drive(drive)

    def _readout(
        self, rates: dict[str, float], dn_spikes: int, early: float, readout_dn: np.ndarray, readout_s: float
    ) -> dict[str, float]:
        """Motor channels from the readout-window statistics (overridden by trained readouts)."""
        decode = decode_motor if self._frame.is_legacy else decode_motor_v2
        return decode(rates, dn_spikes, early)

    def step(self, duration_ms: float) -> NeuralSummary:
        if self._frame is None:
            raise RuntimeError("observe() must be called before step()")
        if not math.isfinite(duration_ms) or duration_ms <= self.readout_start_ms:
            raise ValueError(f"duration_ms must exceed readout start ({self.readout_start_ms} ms)")
        total, bins, wall = self.engine.run(duration_ms, bin_ms=BIN_MS)
        first = int(round(self.readout_start_ms / BIN_MS))
        readout = bins[first:]
        readout_s = readout.shape[0] * BIN_MS / 1000.0

        pop_stats = {}
        specs = spec_by_name()
        rates = {}
        for name, idx in self.populations.items():
            spikes = int(readout[:, idx].sum())
            rate = spikes / (len(idx) * readout_s)
            rates[name] = rate
            pop_stats[name] = {
                "role": specs[name].role,
                "neurons": int(len(idx)),
                "spikes": int(total[idx].sum()),
                "readout_spikes": spikes,
                "rate_hz": round(rate, 4),
                "drive_mv": round(self._drive_by_pop.get(name, 0.0), 4),
            }
        self._rates = rates
        dn_idx = self.populations["DN_all"]
        dn_bins = readout[:, dn_idx].sum(axis=1)
        dn_spikes = int(dn_bins.sum())
        half = len(dn_bins) // 2
        early = float(dn_bins[:half].sum() / dn_spikes) if dn_spikes else 0.5
        readout_dn = readout[:, dn_idx].sum(axis=0).astype(np.float64)
        self._features = np.bincount(self._dn_group, weights=readout_dn) / (self._dn_group_size * readout_s)
        self._features_side = np.bincount(self._dn_group_side, weights=readout_dn) / (
            self._dn_group_side_size * readout_s
        )
        base = (
            decode_motor(rates, dn_spikes, early) if self._frame.is_legacy else decode_motor_v2(rates, dn_spikes, early)
        )
        self._base_channels = base
        channels = self._readout(rates, dn_spikes, early, readout_dn, readout_s)
        self._command = MotorCommand(channels=channels, source=self.info.id)

        per_bin = bins.sum(axis=1)
        active = int(np.count_nonzero(total))
        readouts = [
            {
                **r,
                "spikes": int(total[r["index"]]),
                "rate_hz": round(int(readout[:, r["index"]].sum()) / readout_s, 3),
            }
            for r in self.named
        ]
        summary = NeuralSummary(
            sim_ms=float(duration_ms),
            wall_s=round(wall, 4),
            total_spikes=int(total.sum()),
            active_neurons=active,
            neuron_count=self.engine.n,
            mean_rate_hz=round(float(total.sum()) / (self.engine.n * duration_ms / 1000.0), 5),
            bins=[{"t_ms": round(i * BIN_MS, 3), "spikes": int(s)} for i, s in enumerate(per_bin)],
            populations=pop_stats,
            readouts=readouts,
        )
        self._trace = {
            "bin_ms": BIN_MS,
            "populations": {name: bins[:, idx].sum(axis=1).tolist() for name, idx in self.populations.items()},
            "named": {f"{r['type']}_{r['side']}_{r['id']}": bins[:, r["index"]].tolist() for r in self.named},
        }
        return summary

    def motor_output(self) -> MotorCommand:
        if self._command is None:
            raise RuntimeError("step() must be called before motor_output()")
        return self._command

    def last_trace(self) -> dict | None:
        return self._trace

    def last_features(self, space: str = "dn-type") -> np.ndarray:
        """Per-DN-type mean rates (Hz) over the readout window of the last step; with
        space="dn-type-side", per DN type and soma side."""
        if self._features is None:
            raise RuntimeError("step() must be called before last_features()")
        return self._features_side if space == FEATURE_SPACE_SIDE else self._features

    def feature_names_for(self, space: str = "dn-type") -> list[str]:
        if space not in FEATURE_SPACES:
            raise ValueError(f"unknown feature space {space!r} (known: {FEATURE_SPACES})")
        return [str(n) for n in (self.feature_names_side if space == FEATURE_SPACE_SIDE else self.feature_names)]

    def club_trace(self) -> dict | None:
        """How the last club choice was made (shot telemetry: senses -> DNs -> club_reach -> club)."""
        if self._command is None or "club_reach" not in self._command.channels:
            return None
        return {
            "readout": "fixed",
            "senses": "proxy sensory channels injected into MaleCNS sensory neurons; 400 ms simulated",
            "inputs": "mean rate of all descending neurons (150-400 ms)",
            "dn_all_rate_hz": round(self._rates["DN_all"], 4),
            "rule": f"club_reach = r / (r + {REACH_HALF_HZ:g} Hz), a priori (docs/MOTOR_MAPPING.md)",
            "club_reach": round(self._command.channels["club_reach"], 6),
        }

    def last_fixed_channels(self) -> dict[str, float]:
        """The fixed (untrained) readout's channels for the last step."""
        if self._base_channels is None:
            raise RuntimeError("step() must be called before last_fixed_channels()")
        return self._base_channels
