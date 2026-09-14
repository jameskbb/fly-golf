"""Documented MaleCNS populations: where proxy sensory input is injected and
where motor channels are read out. See docs/SENSORY_MAPPING.md and
docs/MOTOR_MAPPING.md for rationale, citations and caveats.

These are ENGINEERED interface choices. They were written before the first
connectome putt was run, but they were first committed together with that
result, so git history cannot prove the ordering; treat v0.1 as chosen a priori
on the author's word only. Any change must bump the version constants and be
compared against v0.1. They are not claims that these neurons perform these
functions in a real fly playing golf.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MALECNS_SENSORY_MAPPING_VERSION = "malecns-sensory-v0.1"
MALECNS_MOTOR_MAPPING_VERSION = "malecns-motor-v0.1"

# --- Sensory injection -------------------------------------------------------
I_MAX_MV = 30.0  # max drive (mV-equivalent), a Fly Golf choice (first taken from DOOMFLY's photoreceptor current)
SIZE_BASE, SIZE_SPAN = 0.4, 0.6  # target "apparent size": nearer target -> stronger LC10 drive
JO_ALONG_GAIN, JO_LATERAL_GAIN = 0.6, 0.8

# --- Motor readout -----------------------------------------------------------
BIN_MS = 10.0
READOUT_START_MS = 150.0  # ignore onset transient; read the rest of the decision window
STEER_FULL_HZ = 50.0  # DNa01/02 left-right rate difference giving full aim
POWER_HALF_HZ = 2.0  # DN population mean rate giving stroke_power = 0.5
FACE_FULL_HZ = 2.0  # DN population left-right difference giving full face angle
STRIKE_MIN_SPIKES = 5  # DN spikes in the readout window for strike >= 0.5 (contact)

NAMED_READOUT_TYPES = ["DNa01", "DNa02", "DNp09", "MDN", "DNp20", "DNpe017", "DNp01", "DNb05"]


@dataclass(frozen=True)
class PopulationSpec:
    name: str
    role: str  # "sensory" | "motor"
    description: str
    type_prefixes: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    superclass: str | None = None
    side: str | None = None  # "L" | "R" | None
    subclass: str | None = None

    def select(self, neurons: pd.DataFrame) -> np.ndarray:
        mask = np.ones(len(neurons), dtype=bool)
        t = neurons["type"].astype(object).fillna("").astype(str)
        if self.type_prefixes or self.types:
            m = np.zeros(len(neurons), dtype=bool)
            for p in self.type_prefixes:
                m |= t.str.startswith(p).to_numpy()
            if self.types:
                m |= t.isin(self.types).to_numpy()
            mask &= m
        if self.superclass:
            mask &= (neurons["superclass"].astype(object).fillna("") == self.superclass).to_numpy()
        if self.subclass:
            if "subclass" not in neurons.columns:
                return np.zeros(0, dtype=np.int64)
            mask &= (neurons["subclass"].astype(object).fillna("") == self.subclass).to_numpy()
        if self.side:
            mask &= (neurons["side"].astype(object).fillna("") == self.side).to_numpy()
        return np.flatnonzero(mask).astype(np.int64)


SENSORY_POPULATIONS = [
    PopulationSpec(
        "LC10_L",
        "sensory",
        "LC10 visual projection neurons, left optic lobe (target in left field)",
        type_prefixes=("LC10",),
        side="L",
    ),
    PopulationSpec(
        "LC10_R",
        "sensory",
        "LC10 visual projection neurons, right optic lobe (target in right field)",
        type_prefixes=("LC10",),
        side="R",
    ),
    PopulationSpec(
        "JO-C_L",
        "sensory",
        "Johnston's organ JO-C neurons, left antenna (static deflection proxy)",
        type_prefixes=("JO-C",),
        side="L",
    ),
    PopulationSpec(
        "JO-C_R", "sensory", "Johnston's organ JO-C neurons, right antenna", type_prefixes=("JO-C",), side="R"
    ),
    PopulationSpec(
        "JO-E_L",
        "sensory",
        "Johnston's organ JO-E neurons, left antenna (static deflection proxy)",
        type_prefixes=("JO-E",),
        side="L",
    ),
    PopulationSpec(
        "JO-E_R", "sensory", "Johnston's organ JO-E neurons, right antenna", type_prefixes=("JO-E",), side="R"
    ),
]

MOTOR_POPULATIONS = [
    PopulationSpec(
        "steer_L",
        "motor",
        "Steering descending neurons DNa01 + DNa02, left",
        types=("DNa01", "DNa02"),
        side="L",
    ),
    PopulationSpec(
        "steer_R",
        "motor",
        "Steering descending neurons DNa01 + DNa02, right",
        types=("DNa01", "DNa02"),
        side="R",
    ),
    PopulationSpec("DN_L", "motor", "All descending neurons, left soma side", superclass="descending_neuron", side="L"),
    PopulationSpec(
        "DN_R", "motor", "All descending neurons, right soma side", superclass="descending_neuron", side="R"
    ),
    PopulationSpec(
        "DN_all",
        "motor",
        "All descending neurons (brain -> ventral nerve cord output)",
        superclass="descending_neuron",
    ),
]


# --- v0.2 additions (the whole course). Chosen before any v0.2 run; see docs/SENSORY_MAPPING.md.
MALECNS_SENSORY_MAPPING_VERSION_V2 = "malecns-sensory-v0.2"
MALECNS_MOTOR_MAPPING_VERSION_V2 = "malecns-motor-v0.2"
FAR_GAIN = 1.0  # LC15 drive at target_far = 1 (a target ~250 m or more away), as a fraction of I_MAX_MV
ROUGHNESS = {"green": 0.15, "fairway": 0.45, "rough": 0.8, "sand": 1.0}  # tarsal contact proxy per lie
WATER_GAIN = 1.0
REACH_HALF_HZ = 6.0  # DN_all mean rate giving club_reach = 0.5 (see docs/MOTOR_MAPPING.md for the caveat)

SENSORY_POPULATIONS_V2 = [
    PopulationSpec(
        "LC15",
        "sensory",
        "LC15 visual projection neurons, both optic lobes (long-range target cue)",
        type_prefixes=("LC15",),
    ),
    PopulationSpec(
        "leg_bristle",
        "sensory",
        "Leg bristle mechanosensory neurons, VNC (ground texture under the tarsi)",
        superclass="vnc_sensory",
        subclass="leg bristle",
    ),
    PopulationSpec(
        "R7d_R8d",
        "sensory",
        "Dorsal-rim R7d/R8d polarization photoreceptors (stand-in for water glint)",
        types=("R7d", "R8d"),
    ),
]


def all_population_specs() -> list[PopulationSpec]:
    return SENSORY_POPULATIONS + SENSORY_POPULATIONS_V2 + MOTOR_POPULATIONS


def resolve_populations(neurons: pd.DataFrame) -> dict[str, np.ndarray]:
    out = {}
    for spec in all_population_specs():
        out[spec.name] = spec.select(neurons)
    return out


def spec_by_name() -> dict[str, PopulationSpec]:
    return {s.name: s for s in all_population_specs()}


def _clip(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def sensory_drive(channels: dict[str, float]) -> dict[str, float]:
    """Per-population drive (mV-equivalent, applied to every neuron in the population)."""
    size = SIZE_BASE + SIZE_SPAN * (1.0 - channels["target_distance"])
    w_left = 0.5 + 0.5 * (channels["target_left"] - channels["target_right"])
    up, down = channels["slope_uphill"], channels["slope_downhill"]
    fl, fr = channels["slope_fall_left"], channels["slope_fall_right"]
    return {
        "LC10_L": I_MAX_MV * size * w_left,
        "LC10_R": I_MAX_MV * size * (1.0 - w_left),
        "JO-C_L": I_MAX_MV * _clip(JO_ALONG_GAIN * up + JO_LATERAL_GAIN * fl),
        "JO-C_R": I_MAX_MV * _clip(JO_ALONG_GAIN * up + JO_LATERAL_GAIN * fr),
        "JO-E_L": I_MAX_MV * _clip(JO_ALONG_GAIN * down + JO_LATERAL_GAIN * fl),
        "JO-E_R": I_MAX_MV * _clip(JO_ALONG_GAIN * down + JO_LATERAL_GAIN * fr),
    }


def decode_motor(rates: dict[str, float], dn_spikes: int, dn_early_fraction: float) -> dict[str, float]:
    """Motor channels from readout-window population statistics (mean rate per neuron, Hz)."""
    steer = rates["steer_L"] - rates["steer_R"]
    dn = rates["DN_all"]
    lat = rates["DN_L"] - rates["DN_R"]
    return {
        "aim_left": _clip(steer / STEER_FULL_HZ),
        "aim_right": _clip(-steer / STEER_FULL_HZ),
        "stroke_power": dn / (dn + POWER_HALF_HZ) if dn > 0 else 0.0,
        "stroke_tempo": _clip(dn_early_fraction),
        "face_open": _clip(-lat / FACE_FULL_HZ),
        "face_closed": _clip(lat / FACE_FULL_HZ),
        "strike": _clip(dn_spikes / (2.0 * STRIKE_MIN_SPIKES)),
    }


def _lie(channels: dict[str, float]) -> str:
    if channels["lie_sand"] > 0.5:
        return "sand"
    if channels["lie_rough"] > 0.5:
        return "rough"
    if channels["lie_green"] > 0.5:
        return "green"
    return "fairway"


def sensory_drive_v2(channels: dict[str, float]) -> dict[str, float]:
    """v0.1 drive (identical formulas on the nine shared channels) plus three new populations."""
    return sensory_drive(channels) | {
        "LC15": I_MAX_MV * FAR_GAIN * channels["target_far"],
        "leg_bristle": I_MAX_MV * ROUGHNESS[_lie(channels)],
        "R7d_R8d": I_MAX_MV * WATER_GAIN * channels["water_on_line"],
    }


def decode_motor_v2(rates: dict[str, float], dn_spikes: int, dn_early_fraction: float) -> dict[str, float]:
    """v0.1 channels plus club_reach: more descending drive -> reach for a longer club."""
    dn = rates["DN_all"]
    return decode_motor(rates, dn_spikes, dn_early_fraction) | {
        "club_reach": dn / (dn + REACH_HALF_HZ) if dn > 0 else 0.0,
    }
