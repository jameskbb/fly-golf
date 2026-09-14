import math

import numpy as np
import pandas as pd
import pytest

from fly_golf.brain.malecns.transmitters import (
    CONFLICT,
    FAST,
    MODULATOR_ONLY,
    UNRESOLVED,
    classify,
    sign_reasons,
    transmitter_signs,
)

CASES = [
    # label, expected sign (None = ambiguous), reason
    ("acetylcholine", 1, FAST),
    ("gaba", -1, FAST),
    ("glutamate", -1, FAST),
    ("histamine", -1, FAST),
    ("GABA", -1, FAST),
    (" Acetylcholine ", 1, FAST),
    ("acetylcholine,dopamine", 1, FAST),
    ("gaba,glutamate", -1, FAST),
    ("glutamate, serotonin", -1, FAST),
    ("acetylcholine,gaba", None, CONFLICT),
    ("histamine,acetylcholine,octopamine", None, CONFLICT),
    ("dopamine", None, MODULATOR_ONLY),
    ("serotonin", None, MODULATOR_ONLY),
    ("octopamine", None, MODULATOR_ONLY),
    ("tyramine", None, MODULATOR_ONLY),
    ("dopamine,serotonin", None, MODULATOR_ONLY),
    ("unclear", None, UNRESOLVED),
    ("unknown", None, UNRESOLVED),
    ("", None, UNRESOLVED),
    (None, None, UNRESOLVED),
    (math.nan, None, UNRESOLVED),
    (pd.NA, None, UNRESOLVED),
    ("missing", None, UNRESOLVED),
    ("nitric oxide", None, UNRESOLVED),
]


@pytest.mark.parametrize(("label", "sign", "reason"), CASES)
def test_classify(label, sign, reason):
    assert classify(label) == (sign, reason)


@pytest.mark.parametrize("ambiguous_sign", [1, -1])
def test_transmitter_signs_uses_the_configured_ambiguous_sign(ambiguous_sign):
    labels = [c[0] for c in CASES]
    signs, ambiguous = transmitter_signs(labels, ambiguous_sign=ambiguous_sign)
    assert signs.dtype == np.int8 and ambiguous.dtype == bool
    for (_, sign, _), s, a in zip(CASES, signs, ambiguous, strict=True):
        assert a == (sign is None)
        assert s == (ambiguous_sign if sign is None else sign)


@pytest.mark.parametrize("bad", [0, 2, -2, None])
def test_ambiguous_sign_must_be_plus_or_minus_one(bad):
    with pytest.raises(ValueError):
        transmitter_signs(["gaba"], ambiguous_sign=bad)


def test_every_neuron_gets_a_sign_and_nothing_is_dropped():
    labels = pd.Series(["acetylcholine", None, "dopamine", "gaba", "unclear"], dtype="string")
    signs, ambiguous = transmitter_signs(labels)
    assert len(signs) == len(labels)
    assert signs.tolist() == [1, 1, 1, -1, 1]
    assert ambiguous.tolist() == [False, True, True, False, True]


def test_sign_reasons_counts_each_rule():
    labels = ["acetylcholine", "gaba", "acetylcholine,gaba", "serotonin", "unclear", None]
    assert sign_reasons(labels) == {CONFLICT: 1, FAST: 2, MODULATOR_ONLY: 1, UNRESOLVED: 2}


def test_empty_input():
    signs, ambiguous = transmitter_signs([])
    assert signs.shape == (0,) and ambiguous.shape == (0,)
