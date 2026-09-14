"""A TRAINED readout of MaleCNS descending-neuron activity.

The connectome, the LIF dynamics and the sensory injection are exactly those of
`MaleCNSController` (malecns-sensory-v0.2). What changes is how three motor channels are read
out of the brain's output layer. `features` are the mean firing rates of every descending-neuron
TYPE during the readout window (the brain's output to the body, ~480 types) and z() is a fixed
log/standardise transform. Two readout formats exist:

* v1 (`fly-golf-linear-readout-v1`): one linear map, (aim, stroke_power, club_reach) = W z + b.
* v2 (`fly-golf-gated-readout-v2`, current): a PUTTER GATE, p(putter) = sigmoid(w_g z + b_g);
  when it says swing, a CLUB head, club index = round(w_c z + b_c) clipped to the 13 lofted
  clubs; and two linear (aim, stroke_power) heads, one for the putter and one for full swings,
  of which the gate picks one.

Every number that reaches the body is a function of the DN rates only. W, b were fitted offline
by `fly-golf train` (docs/TRAINING.md); tempo, face and strike still come from the fixed v0.2
readout. Nothing here sees golf state: the weights are frozen and the input is the neural
activity evoked by the sensory frame.

This is reservoir-style readout learning, not plasticity inside the connectome: the synaptic
weights of the MaleCNS graph are never changed. It is labeled TRAINED everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..golf.clubs import BAG, reach_for
from .interfaces import ControllerInfo, ControllerKind
from .malecns.controller import MaleCNSController
from .malecns.engine import ENGINE_VERSION
from .malecns.graph import CompiledGraph

# Every readout made before `fly-golf-lif-v1` existed was fitted to the legacy engine's activity.
LEGACY_ENGINE_VERSION = "lif-doomfly-r2-adapted-v1"

READOUT_FORMAT = "fly-golf-linear-readout-v1"
READOUT_FORMAT_V2 = "fly-golf-gated-readout-v2"
OUTPUTS = ("aim", "stroke_power", "club_reach")
HEADS = ("putter", "swing")  # v2 (aim, stroke_power) heads, chosen by the predicted club
N_CLUBS = len(BAG)


def feature_transform(x: np.ndarray) -> np.ndarray:
    """Rates (Hz) -> log(1 + rate): tames the heavy tail of a few very active DN types."""
    return np.log1p(np.maximum(np.asarray(x, dtype=np.float64), 0.0))


def _standardise(x: np.ndarray, transform: str, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    xt = feature_transform(x) if transform == "log1p" else np.asarray(x, dtype=np.float64)
    return (xt - mean) / scale


def _rounded(a: np.ndarray) -> list:
    return np.round(np.asarray(a, dtype=np.float64), 9).tolist()


def sigmoid(x):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(x, dtype=np.float64)))


def swing_club_index(raw) -> np.ndarray | int:
    """Club-head output (a club index on the bag's distance order) -> one of the 13 lofted clubs."""
    return np.clip(np.rint(raw), 1, N_CLUBS - 1).astype(int)


@dataclass
class LinearReadout:
    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray  # [len(OUTPUTS), n_features] on standardised features
    bias: np.ndarray  # [len(OUTPUTS)]
    meta: dict = field(default_factory=dict)
    transform: str = "log1p"

    def predict_raw(self, x: np.ndarray) -> np.ndarray:
        return self.weights @ _standardise(x, self.transform, self.mean, self.scale) + self.bias

    def predict(self, x: np.ndarray) -> dict[str, float]:
        y = self.predict_raw(x)
        return {
            "aim": float(np.clip(y[0], -1.0, 1.0)),
            "stroke_power": float(np.clip(y[1], 0.0, 1.0)),
            "club_reach": float(np.clip(y[2], 0.0, 1.0)),
        }

    def to_json(self) -> dict:
        return {
            "format": READOUT_FORMAT,
            "outputs": list(OUTPUTS),
            "transform": self.transform,
            "feature_names": list(self.feature_names),
            "mean": _rounded(self.mean),
            "scale": _rounded(self.scale),
            "weights": _rounded(self.weights),
            "bias": _rounded(self.bias),
            "meta": self.meta,
        }

    @staticmethod
    def from_json(d: dict) -> LinearReadout:
        if d.get("format") != READOUT_FORMAT:
            raise ValueError(f"unknown readout format {d.get('format')!r}")
        if list(d["outputs"]) != list(OUTPUTS):
            raise ValueError("readout outputs do not match this code")
        return LinearReadout(
            feature_names=list(d["feature_names"]),
            mean=np.asarray(d["mean"], dtype=np.float64),
            scale=np.asarray(d["scale"], dtype=np.float64),
            weights=np.asarray(d["weights"], dtype=np.float64),
            bias=np.asarray(d["bias"], dtype=np.float64),
            meta=dict(d.get("meta", {})),
            transform=d.get("transform", "log1p"),
        )

    @staticmethod
    def load(path: Path) -> LinearReadout:
        return LinearReadout.from_json(json.loads(Path(path).read_text()))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n")


@dataclass
class GatedReadout:
    """v2: putter gate + club head + gated (aim, power) heads, all linear in z(DN rates)."""

    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    gate_weights: np.ndarray  # [n_features]: logit of "this is a putt"
    gate_bias: float
    club_weights: np.ndarray  # [n_features]: club index (1 = lob wedge ... 13 = driver) for swings
    club_bias: float
    head_weights: dict[str, np.ndarray]  # head -> [2, n_features] for (aim, stroke_power)
    head_bias: dict[str, np.ndarray]  # head -> [2]
    # Decoding calibration, chosen by practice after the fit (docs/TRAINING.md, step 5): the club
    # head's output is stretched about `club_center` and shifted (+ shift = shorter clubs), and
    # each head's power is scaled. The defaults are the identity.
    club_center: float = 7.0
    club_stretch: float = 1.0
    club_shift: float = 0.0
    power_scale: dict[str, float] = field(default_factory=lambda: {h: 1.0 for h in HEADS})
    meta: dict = field(default_factory=dict)
    transform: str = "log1p"

    def z(self, x: np.ndarray) -> np.ndarray:
        return _standardise(x, self.transform, self.mean, self.scale)

    def club_raw(self, z: np.ndarray) -> float:
        """The club head's uncalibrated output (a club index, before rounding)."""
        return float(self.club_weights @ z + self.club_bias)

    def predict(self, x: np.ndarray) -> dict:
        z = self.z(x)
        p_putt = float(sigmoid(self.gate_weights @ z + self.gate_bias))
        if p_putt >= 0.5:
            k, head = 0, "putter"
        else:
            raw = self.club_raw(z)
            calibrated = self.club_center + self.club_stretch * (raw - self.club_center) - self.club_shift
            k = int(swing_club_index(calibrated))
            head = "swing"
        aim, power = self.head_weights[head] @ z + self.head_bias[head]
        power *= self.power_scale[head]
        return {
            "aim": float(np.clip(aim, -1.0, 1.0)),
            "stroke_power": float(np.clip(power, 0.0, 1.0)),
            "club_reach": reach_for(BAG[k]),
            "club": BAG[k].id,
            "p_putt": round(p_putt, 6),
            "head": head,
            "club_head_raw": None if head == "putter" else round(raw, 6),
            "club_head_calibrated": None if head == "putter" else round(float(calibrated), 6),
        }

    def to_json(self) -> dict:
        return {
            "format": READOUT_FORMAT_V2,
            "outputs": list(OUTPUTS),
            "clubs": [c.id for c in BAG],
            "heads": list(HEADS),
            "transform": self.transform,
            "feature_names": list(self.feature_names),
            "mean": _rounded(self.mean),
            "scale": _rounded(self.scale),
            "gate_weights": _rounded(self.gate_weights),
            "gate_bias": round(float(self.gate_bias), 9),
            "club_weights": _rounded(self.club_weights),
            "club_bias": round(float(self.club_bias), 9),
            "head_weights": {h: _rounded(self.head_weights[h]) for h in HEADS},
            "head_bias": {h: _rounded(self.head_bias[h]) for h in HEADS},
            "calibration": {
                "club_center": round(float(self.club_center), 9),
                "club_stretch": float(self.club_stretch),
                "club_shift": float(self.club_shift),
                "power_scale": {h: float(self.power_scale[h]) for h in HEADS},
            },
            "meta": self.meta,
        }

    @staticmethod
    def from_json(d: dict) -> GatedReadout:
        if d.get("format") != READOUT_FORMAT_V2:
            raise ValueError(f"unknown readout format {d.get('format')!r}")
        if list(d["clubs"]) != [c.id for c in BAG]:
            raise ValueError("readout was trained for a different bag")
        if list(d["heads"]) != list(HEADS):
            raise ValueError("readout heads do not match this code")
        cal = d.get("calibration") or {}
        return GatedReadout(
            feature_names=list(d["feature_names"]),
            mean=np.asarray(d["mean"], dtype=np.float64),
            scale=np.asarray(d["scale"], dtype=np.float64),
            gate_weights=np.asarray(d["gate_weights"], dtype=np.float64),
            gate_bias=float(d["gate_bias"]),
            club_weights=np.asarray(d["club_weights"], dtype=np.float64),
            club_bias=float(d["club_bias"]),
            head_weights={h: np.asarray(d["head_weights"][h], dtype=np.float64) for h in HEADS},
            head_bias={h: np.asarray(d["head_bias"][h], dtype=np.float64) for h in HEADS},
            club_center=float(cal.get("club_center", 7.0)),
            club_stretch=float(cal.get("club_stretch", 1.0)),
            club_shift=float(cal.get("club_shift", 0.0)),
            power_scale={h: float(cal.get("power_scale", {}).get(h, 1.0)) for h in HEADS},
            meta=dict(d.get("meta", {})),
            transform=d.get("transform", "log1p"),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n")


Readout = LinearReadout | GatedReadout


def readout_from_json(d: dict) -> Readout:
    if d.get("format") == READOUT_FORMAT_V2:
        return GatedReadout.from_json(d)
    return LinearReadout.from_json(d)


def load_readout(path: Path) -> Readout:
    return readout_from_json(json.loads(Path(path).read_text()))


def readout_engine(meta: dict) -> str:
    """The neural engine whose activity a readout was fitted to."""
    return meta.get("neural_engine") or LEGACY_ENGINE_VERSION


def trained_channels(fixed: dict[str, float], pred: dict) -> dict[str, float]:
    """Merge a readout prediction into the fixed readout's channels."""
    aim = pred["aim"]
    return fixed | {
        "aim_left": max(aim, 0.0),
        "aim_right": max(-aim, 0.0),
        "stroke_power": pred["stroke_power"],
        "club_reach": pred["club_reach"],
    }


class TrainedReadoutController(MaleCNSController):
    """Runs on the engine the readout was trained against; refuses any other (docs/TRAINING.md)."""

    def __init__(
        self, graph: CompiledGraph, readout: Readout, readout_path: str | None = None, engine: str | None = None
    ):
        trained_on = readout_engine(readout.meta)
        if engine is not None and engine != trained_on:
            raise ValueError(
                f"readout {readout.meta.get('training_id')!r} was trained on neural engine {trained_on!r}; "
                f"refusing to run it on {engine!r} (retrain it, or use the engine it was trained on)"
            )
        super().__init__(graph, engine=trained_on)
        if list(readout.feature_names) != [str(n) for n in self.feature_names]:
            raise ValueError("readout was trained on a different set of descending-neuron types")
        self.readout = readout
        self.last_prediction: dict | None = None
        base = self.info
        gated = isinstance(readout, GatedReadout)
        self.info = ControllerInfo(
            id="malecns-trained",
            kind=ControllerKind.MALECNS,
            label="MaleCNS + TRAINED READOUT",
            is_mock=False,
            description=(
                "The same MaleCNS v1.0 connectome simulation. Club, aim and power are read out of "
                "descending-neuron activity by weights fitted offline from practice shots "
                + ("(a putter gate, a club head and putter / full-swing heads; " if gated else "(")
                + "docs/TRAINING.md). The connectome's synapses are unchanged."
            ),
            neuron_count=base.neuron_count,
            edge_count=base.edge_count,
            connectome=base.connectome,
            model=base.model,
            config=base.config
            | {
                "readout": {
                    "path": readout_path,
                    "format": READOUT_FORMAT_V2 if gated else READOUT_FORMAT,
                    "id": readout.meta.get("training_id"),
                    "neural_engine": trained_on,
                    "current_engine": trained_on == ENGINE_VERSION,
                    "method": readout.meta.get("method"),
                    "trained_utc": readout.meta.get("created_utc"),
                    "git_commit": (readout.meta.get("git") or {}).get("commit"),
                    "test_metrics": readout.meta.get("test_summary"),
                    "situations": readout.meta.get("situations"),
                    "calibration": (readout.meta.get("fit") or {}).get("calibration"),
                    "bench": readout.meta.get("bench"),
                }
            },
        )

    def _readout(self, rates, dn_spikes, early, readout_dn, readout_s):
        fixed = super()._readout(rates, dn_spikes, early, readout_dn, readout_s)
        if self._frame.is_legacy:
            return fixed  # the trained readout is defined for v0.2 frames only
        self.last_prediction = self.readout.predict(self._features)
        return trained_channels(fixed, self.last_prediction)

    def club_trace(self) -> dict | None:
        if self._frame is None or self._frame.is_legacy or self.last_prediction is None:
            return super().club_trace()
        p = self.last_prediction
        gated = isinstance(self.readout, GatedReadout)
        return {
            "readout": "trained",
            "format": READOUT_FORMAT_V2 if gated else READOUT_FORMAT,
            "readout_id": self.readout.meta.get("training_id"),
            "senses": "proxy sensory channels injected into MaleCNS sensory neurons; 400 ms simulated",
            "inputs": f"{len(self.feature_names)} descending-neuron type rates (150-400 ms)",
            "dn_all_rate_hz": round(self._rates["DN_all"], 4),
            "p_putt": p.get("p_putt"),
            "gate": p.get("head"),
            "club_head_raw": p.get("club_head_raw"),
            "club_head_calibrated": p.get("club_head_calibrated"),
            "rule": (
                "putter if p_putt >= 0.5, else club index = round(calibrated club head), lob wedge..driver"
                if gated
                else "club_reach = linear readout of z(DN rates), clipped to [0, 1]"
            ),
            "club_reach": round(p["club_reach"], 6),
        }
