"""Neurotransmitter -> synaptic sign: Fly Golf's coarse fast-transmission proxy.

Every edge of the compiled graph gets the sign of its presynaptic neuron's transmitter, as
predicted by the MaleCNS release (`consensus_nt`):

    acetylcholine                  -> excitatory (+1)
    GABA, glutamate, histamine     -> inhibitory (-1)

A label naming several transmitters is resolved by its fast transmitters: if they all have the
same sign, that sign is used. Anything else is *ambiguous* and gets the configured
`ambiguous_sign` (+1 in Fly Golf): conflicting fast signs, only modulators (dopamine,
serotonin, octopamine, tyramine), an "unclear" prediction or no prediction at all. Ambiguous
edges are never deleted.

This is a coarse modelling proxy, not receptor-level physiology: glutamate is excitatory at some
fly synapses, receptor types are ignored, and modulators act on slower time scales than any
sign can express. See docs/PROVENANCE.md.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import numpy as np
import pandas as pd

EXCITATORY = 1
INHIBITORY = -1
DEFAULT_AMBIGUOUS_SIGN = EXCITATORY
SIGN_MODEL = "ACh +; GABA/Glu/His -; conflicting, modulator-only, unclear or missing -> ambiguous sign"

FAST_SIGN = {
    "acetylcholine": EXCITATORY,
    "gaba": INHIBITORY,
    "glutamate": INHIBITORY,
    "histamine": INHIBITORY,
}
MODULATORS = frozenset({"dopamine", "serotonin", "octopamine", "tyramine"})

# Why a neuron's sign was (or was not) determined.
FAST = "fast"
CONFLICT = "conflicting_fast_signs"
MODULATOR_ONLY = "modulator_only"
UNRESOLVED = "unclear_or_missing"


def _names(label) -> set[str]:
    """The transmitter names in a label ("gaba", "acetylcholine,dopamine"); empty if missing."""
    if label is None or (not isinstance(label, str) and pd.isna(label)):
        return set()
    return {part.strip().lower() for part in str(label).split(",") if part.strip()}


def classify(label) -> tuple[int | None, str]:
    """(sign, reason) for one transmitter label; sign is None when the label is ambiguous."""
    names = _names(label)
    fast_signs = {FAST_SIGN[name] for name in names if name in FAST_SIGN}
    if len(fast_signs) == 1:
        return fast_signs.pop(), FAST
    if fast_signs:
        return None, CONFLICT
    if names & MODULATORS:
        return None, MODULATOR_ONLY
    return None, UNRESOLVED


def transmitter_signs(labels: Iterable, ambiguous_sign: int = DEFAULT_AMBIGUOUS_SIGN) -> tuple[np.ndarray, np.ndarray]:
    """Per-neuron signs (int8, +1 / -1) and a mask of the neurons given `ambiguous_sign`."""
    if ambiguous_sign not in (EXCITATORY, INHIBITORY):
        raise ValueError("ambiguous_sign must be +1 or -1: ambiguous edges stay in the graph")
    calls = [classify(label)[0] for label in labels]
    ambiguous = np.fromiter((c is None for c in calls), dtype=bool, count=len(calls))
    signs = np.fromiter((ambiguous_sign if c is None else c for c in calls), dtype=np.int8, count=len(calls))
    return signs, ambiguous


def sign_reasons(labels: Iterable) -> dict[str, int]:
    """How many neurons fall under each rule (recorded in the compiled graph's manifest)."""
    return dict(sorted(Counter(classify(label)[1] for label in labels).items()))
