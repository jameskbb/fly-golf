"""Regenerate tests/fixtures/lif_reference.json: the LIF parity scenarios run on

* the Brian2 reference simulator with the Shiu et al. (2024) model equations (the oracle), and
* the legacy engine `lif-doomfly-r2-adapted-v1` (frozen, so its behaviour cannot drift).

Brian2 is not a Fly Golf dependency. Run with the optional `reference` group:

    uv --directory services/sim run --group reference python scripts/generate_lif_reference.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))

from fly_golf.brain.malecns.engine import DEFAULT_PARAMETERS  # noqa: E402
from fly_golf.brain.malecns.legacy_engine import ENGINE_VERSION as LEGACY_VERSION  # noqa: E402
from fly_golf.brain.malecns.legacy_engine import LIFEngine as LegacyLIFEngine  # noqa: E402
from lif_scenarios import DT_MS, SCENARIOS, csr, definition, drive_vector, run_scenario  # noqa: E402

OUT = HERE.parent / "tests" / "fixtures" / "lif_reference.json"

# The model exactly as in the reference implementation (Shiu et al. `model.py`), plus Fly Golf's
# constant drive term inside dv/dt.
EQUATIONS = """
dv/dt = (v_0 - v + g + drive) / t_mbr : volt (unless refractory)
dg/dt = -g / tau : volt (unless refractory)
drive : volt
"""


def run_brian2(scenario: dict) -> dict:
    import brian2 as b2

    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = DT_MS * b2.ms
    p = DEFAULT_PARAMETERS
    namespace = {
        "v_0": p.v_rest_mv * b2.mV,
        "t_mbr": p.tau_m_ms * b2.ms,
        "tau": p.tau_g_ms * b2.ms,
        "v_th": p.v_threshold_mv * b2.mV,
        "v_rst": p.v_reset_mv * b2.mV,
    }
    n = scenario["n"]
    neurons = b2.NeuronGroup(
        n,
        EQUATIONS,
        method="linear",
        threshold="v > v_th",
        reset="v = v_rst; g = 0 * mV",
        refractory=p.refractory_ms * b2.ms,
        namespace=namespace,
    )
    neurons.v = p.v_rest_mv * b2.mV
    neurons.g = 0 * b2.mV
    objects = [neurons]
    ptr, post, weight = csr(scenario)
    if len(post):
        pre = np.repeat(np.arange(n), np.diff(ptr))
        synapses = b2.Synapses(neurons, neurons, "w : volt", on_pre="g_post += w", delay=p.delay_ms * b2.ms)
        synapses.connect(i=pre, j=post.astype(np.int64))
        synapses.w = weight.astype(np.float64) * b2.mV
        objects.append(synapses)
    monitor = b2.SpikeMonitor(neurons)
    objects.append(monitor)
    net = b2.Network(*objects)
    v_end, g_end = [], []
    for drive, ms in scenario["phases"]:
        neurons.drive = drive_vector(n, drive) * b2.mV
        net.run(ms * b2.ms)
        v_end.append([float(x) for x in neurons.v[:] / b2.mV])
        g_end.append([float(x) for x in neurons.g[:] / b2.mV])
    spikes = sorted(
        [int(round(float(t) / DT_MS)), int(i)] for i, t in zip(monitor.i[:], monitor.t[:] / b2.ms, strict=True)
    )
    return {"spikes": spikes, "v_end": v_end, "g_end": g_end}


def main() -> int:
    import brian2 as b2

    results = {}
    for name, scenario in SCENARIOS.items():
        ref = run_brian2(scenario)
        legacy = run_scenario(LegacyLIFEngine(*csr(scenario)), scenario)
        results[name] = {
            "about": scenario["about"],
            "definition": definition(scenario),
            "brian2": ref,
            "legacy": legacy,
        }
        same = ref["spikes"] == legacy["spikes"]
        print(f"{name:28s} brian2 {len(ref['spikes']):5d} spikes   legacy {len(legacy['spikes']):5d}  same={same}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "generator": "services/sim/scripts/generate_lif_reference.py",
                "brian2_version": b2.__version__,
                "brian2_method": "linear",
                "equations": EQUATIONS.strip(),
                "legacy_engine": LEGACY_VERSION,
                "dt_ms": DT_MS,
                "scenarios": results,
            },
            indent=None,
            separators=(",", ":"),
        )
        + "\n"
    )
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
