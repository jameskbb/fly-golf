"""Controller-facing data types and the BrainController protocol.

The controller sees ONLY a `SensoryFrame` (bounded channels) and emits ONLY a
`MotorCommand` (bounded channels). It never receives golf state, the cup
position, or a precomputed aim/power, and it never calls physics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# v0.1 channel sets: the putting-only slice. Kept so recorded v0.1 shots stay valid and replayable.
LEGACY_SENSORY_CHANNELS: tuple[str, ...] = (
    "target_left",
    "target_right",
    "target_distance",
    "slope_uphill",
    "slope_downhill",
    "slope_fall_left",
    "slope_fall_right",
    "green_speed",
    "ball_at_rest",
)

# v0.2 (current): v0.1 + long-range distance, the lie under the fly's feet, and water on the line.
SENSORY_CHANNELS: tuple[str, ...] = LEGACY_SENSORY_CHANNELS + (
    "target_far",
    "lie_green",
    "lie_rough",
    "lie_sand",
    "water_on_line",
)

LEGACY_MOTOR_CHANNELS: tuple[str, ...] = (
    "aim_left",
    "aim_right",
    "stroke_power",
    "stroke_tempo",
    "face_open",
    "face_closed",
    "strike",
)

# motor-mapping-v2 (current): v1 + the club the fly reaches for (0 = putter ... 1 = driver).
MOTOR_CHANNELS: tuple[str, ...] = LEGACY_MOTOR_CHANNELS + ("club_reach",)

SENSORY_CHANNELS_BY_VERSION: dict[str, tuple[str, ...]] = {
    "proxy-sensory-v0.1": LEGACY_SENSORY_CHANNELS,
    "proxy-sensory-v0.2": SENSORY_CHANNELS,
}


def _expected_for(values: Mapping[str, float], known: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    """Pick the channel set whose names match `values` exactly (else the current set, for the error)."""
    if isinstance(values, Mapping):
        for chans in known:
            if set(values) == set(chans):
                return chans
    return known[-1]


def _validate_channels(values: Mapping[str, float], expected: tuple[str, ...], what: str) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{what} must be a mapping of channel -> value")
    keys = set(values)
    missing = [k for k in expected if k not in keys]
    extra = sorted(keys - set(expected))
    if missing or extra:
        raise ValueError(f"{what} channel mismatch: missing={missing} unexpected={extra}")
    out: dict[str, float] = {}
    for k in expected:
        v = values[k]
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise ValueError(f"{what} channel {k!r} must be a number, got {type(v).__name__}")
        v = float(v)
        if not math.isfinite(v) or v < 0.0 or v > 1.0:
            raise ValueError(f"{what} channel {k!r}={v} outside [0, 1]")
        out[k] = v
    return out


@dataclass(frozen=True)
class SensoryFrame:
    channels: Mapping[str, float]
    encoder: str
    version: str

    def __post_init__(self) -> None:
        expected = SENSORY_CHANNELS_BY_VERSION.get(self.version) or _expected_for(
            self.channels, (LEGACY_SENSORY_CHANNELS, SENSORY_CHANNELS)
        )
        object.__setattr__(self, "channels", _validate_channels(self.channels, expected, "sensory"))

    @property
    def is_legacy(self) -> bool:
        return len(self.channels) == len(LEGACY_SENSORY_CHANNELS)

    def to_dict(self) -> dict:
        return {"channels": dict(self.channels), "encoder": self.encoder, "version": self.version}


@dataclass(frozen=True)
class MotorCommand:
    channels: Mapping[str, float]
    source: str  # controller id that produced it

    def __post_init__(self) -> None:
        expected = _expected_for(self.channels, (LEGACY_MOTOR_CHANNELS, MOTOR_CHANNELS))
        object.__setattr__(self, "channels", _validate_channels(self.channels, expected, "motor"))

    def to_dict(self) -> dict:
        return {"channels": dict(self.channels), "source": self.source}


class ControllerKind(StrEnum):
    MOCK = "mock"
    MALECNS = "malecns"


@dataclass(frozen=True)
class ControllerInfo:
    id: str
    kind: ControllerKind
    label: str  # shown in the UI badge, e.g. "MOCK CONTROLLER"
    is_mock: bool
    description: str
    neuron_count: int | None = None
    edge_count: int | None = None
    connectome: str | None = None
    model: str | None = None
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "label": self.label,
            "is_mock": self.is_mock,
            "description": self.description,
            "neuron_count": self.neuron_count,
            "edge_count": self.edge_count,
            "connectome": self.connectome,
            "model": self.model,
            "config": self.config,
        }


@dataclass
class NeuralSummary:
    """Lightweight neural statistics for one decision window (never full traces)."""

    sim_ms: float
    wall_s: float
    total_spikes: int
    active_neurons: int
    neuron_count: int
    mean_rate_hz: float
    bins: list[dict]  # [{"t_ms": float, "spikes": int}]
    populations: dict[str, dict]  # name -> {"role", "neurons", "spikes", "rate_hz"}
    readouts: list[dict] = field(default_factory=list)  # named-cell readouts for the technical panel

    def to_dict(self) -> dict:
        return {
            "sim_ms": self.sim_ms,
            "wall_s": self.wall_s,
            "total_spikes": self.total_spikes,
            "active_neurons": self.active_neurons,
            "neuron_count": self.neuron_count,
            "mean_rate_hz": self.mean_rate_hz,
            "bins": self.bins,
            "populations": self.populations,
            "readouts": self.readouts,
        }


@runtime_checkable
class BrainController(Protocol):
    info: ControllerInfo

    def reset(self, seed: int) -> None:
        """Return to the initial state for a new hole (deterministic given seed)."""

    def observe(self, frame: SensoryFrame) -> None:
        """Receive the current sensory frame (replaces any previous input)."""

    def step(self, duration_ms: float) -> NeuralSummary | None:
        """Advance internal dynamics for one decision window. Mocks return None."""

    def motor_output(self) -> MotorCommand:
        """Motor channels decoded at the end of the last window."""
