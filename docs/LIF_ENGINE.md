# The neural engine (`fly-golf-lif-v1`)

Fly Golf simulates every retained MaleCNS v1.0 neuron with a leaky integrate-and-fire (LIF)
model. The engine is `services/sim/src/fly_golf/brain/malecns/engine.py`, written for Fly Golf
from the published model specification below. It replaced the adapted DOOMFLY kernel
(`lif-doomfly-r2-adapted-v1`), which is kept, unchanged, for replaying old records and running
readouts that were trained on it (see [Legacy engine](#legacy-engine)).

## The model: where each piece comes from

The primary specification is the whole-brain LIF model of Shiu *et al.* (2024, *Nature* 634,
210–219), as defined by its reference implementation (`model.py` in
[philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model), Brian2,
MIT):

```
dv/dt = (V_rest - v + g + I) / tau_m       (unless refractory)
dg/dt = -g / tau_g                          (unless refractory)
threshold: v > V_th         reset: v <- V_reset, g <- 0         refractory: t_ref
on a presynaptic spike: g_post += w, after the delay t_dly
```

| Quantity | Value | Kind | Source |
| --- | --- | --- | --- |
| `tau_m` (membrane time constant) | 20 ms | published model parameter | Shiu et al. (from Kakaria & de Bivort 2017) |
| `tau_g` (synaptic time constant) | 5 ms | published model parameter | Shiu et al. (from Jürgensen et al.) |
| `V_rest` | −52 mV | published model parameter | Shiu et al. |
| `V_reset` | −52 mV | published model parameter | Shiu et al. |
| `V_th` | −45 mV | published model parameter | Shiu et al. |
| refractory period | 2.2 ms | published model parameter | Shiu et al. (from Lazar et al.) |
| synaptic delay | 1.8 ms | published model parameter | Shiu et al. (from Paul et al. 2015) |
| per-synapse weight | 0.275 mV × synapse count × sign | published model parameter (a free parameter there) | Shiu et al.; applied at compile time |
| sign | ACh +, GABA / glutamate / histamine −, ambiguous + | Fly Golf modelling choice | `transmitters.py`, [PROVENANCE.md](PROVENANCE.md) |
| `dt` | 0.1 ms | reference simulation setting | Shiu et al. |
| external input `I` | constant per neuron, per 400 ms decision window | **Fly Golf choice** (the reference uses Poisson input) | [SENSORY_MAPPING.md](SENSORY_MAPPING.md) |
| driven neurons are refractory too | yes | **Fly Golf choice** (the reference sets `t_ref = 0` for Poisson-driven cells) | keeps one rule for every neuron |
| integration | exact solution of the linear system over each `dt` | reference method (`method='linear'`) | derived below |
| state precision | float64 | as the reference (Brian2 default) | |
| weights | stored as float32 in `weight.npy` | Fly Golf storage format | `data/compiler.py` |
| initial state | every neuron at rest, `g = 0`, before each stroke | Fly Golf choice | reproducibility |

## Integration and event order

Between spikes the system is linear, so each step uses its exact solution. With
`u = v − (V_rest + I)`:

```
u' = u · exp(−dt/tau_m) + g · p_vg          g' = g · exp(−dt/tau_g)
p_vg = tau_g / (tau_g − tau_m) · (exp(−dt/tau_g) − exp(−dt/tau_m))      ( = (dt/tau) exp(−dt/tau) if equal )
```

`p_vg` comes from the particular solution `A·exp(−t/tau_g)` of `du/dt = (−u + g)/tau_m` with
`g = g0·exp(−t/tau_g)`, which gives `A = g0·tau_g/(tau_g − tau_m)`. A test checks it against a
200,000-substep numerical integration.

One time step follows Brian2's default schedule (groups, thresholds, synapses, resets):

1. every non-refractory neuron is integrated;
2. every neuron with `v > V_th` spikes;
3. spikes emitted 18 steps ago (1.8 ms) are delivered: `g_post += w`;
4. this step's spikers are reset (`v = V_reset`, `g = 0`).

A spike at step `s` therefore reaches `g` at step `s + 18` and first moves `v` at `s + 19`.

**"Unless refractory."** A neuron is refractory while `(step − last spike) < 22`, so it integrates
again 22 steps after spiking. During that time `v` and `g` are frozen *and synaptic arrivals are
ignored*. That last point matters: Brian2 does not let a synapse write a variable whose equation
is flagged `(unless refractory)`. We checked this directly in Brian2 2.10.1: an arrival during
refractoriness leaves `g` at 0. A consequence: with a 1.8 ms delay and a 2.2 ms refractory period,
a self-edge (autapse) always arrives while its neuron is refractory and never has an effect.

## Implementation choices (performance and determinism)

These are ours and do not change the model:

- **Ascending neuron order.** Within a step, neurons are integrated, and spikes are delivered, in
  ascending neuron index. The order of floating-point additions into `g` therefore never depends
  on history or on the order of edges within a CSR row (tested).
- **Skip the fixed point.** A neuron exactly at rest, with `g = 0` and no drive, is skipped: its
  exact update would return the same values bit for bit. This is the only optimisation in the
  integration loop, and it is exact.
- **Delay ring.** Spikes wait in a ring of 19 slots (delay + 1), one list per step.
- **One compiled kernel call per run.** It counts spikes straight into the requested time bins.
  No random numbers, no threads and no hidden state: `reset()` returns the engine to the state of
  a new one.

## Validation

`tests/test_lif_parity.py` and `tests/test_engine.py`:

| Check | Result |
| --- | --- |
| 16 small networks (one isolated neuron, a driven neuron, excitatory and inhibitory pairs, a feed-forward chain, excitatory and inhibitory loops, refractory saturation, an arrival during refractoriness, delayed delivery, mixed signs, a self edge, simultaneous spikes, a 500 ms quiet period, changing drive, a 40-neuron random network) against **Brian2** running the reference equations | **identical spike trains** (every neuron, every 0.1 ms step); `v` and `g` within 7e-13 mV |
| Two further random networks, simulated live in Brian2 when it is installed | identical |
| Closed-form spike times of a driven neuron, inter-spike interval `21 + k` steps, arrival step `+18`, first effect on `v` at `+19`, frozen state and ignored input while refractory, the propagator | exact |
| Running in pieces equals one run; edge order within a row does not matter; `reset()` | exact |
| **The full MaleCNS graph** (166,700 neurons, 25,582,938 edges), 24 practice situations (putts, course-green putts, chips, full shots), 400 ms each, same drive, against Brian2 | **identical per-neuron spike counts in 24 of 24 situations** |
| A 1e-9 mV perturbation of one neuron's drive on the full graph | no change in any spike count (the simulation is not balanced on a knife edge) |

The Brian2 results are frozen in `tests/fixtures/lif_reference.json` (regenerate with
`uv run --group reference python scripts/generate_lif_reference.py`), so CI needs neither Brian2
nor the connectome. Brian2 is an optional `reference` dependency group, never a runtime one.

## Legacy engine

`legacy_engine.py` (`lif-doomfly-r2-adapted-v1`) is the kernel adapted from DOOMFLY (MIT),
unchanged except for its docstring. It follows the same equations and event order, but keeps `v`
and `g` in **float32** and orders deliveries by when neurons first became active.

| Comparison, full MaleCNS graph, same 24 situations | Legacy | `fly-golf-lif-v1` |
| --- | --- | --- |
| Per-neuron spike counts identical to Brian2 | 2 of 24 (the two silent situations) | **24 of 24** |
| Neurons whose spike count differs from Brian2 (median) | 7,815 of 166,700 | 0 |
| Wall time per 400 ms decision window, one core | 1.82 s | **1.15 s** |

On the 16 small networks the legacy engine matches Brian2 on 15; it parts from it on the
40-neuron random network, where float32 rounding eventually moves a spike by a step and the
difference spreads. On the full graph the same thing happens within a few tens of
milliseconds. Total activity is almost unchanged (median 0.6 % difference in total spikes), but
the **correlation between the two engines' descending-neuron type rates is only 0.84–0.99**
(median 0.978), and the fixed readout's aim and face channels move by up to 0.4–0.5.

That is a material change for anything fitted to those rates. So:

- `fly-golf-lif-v1` is the engine for every new shot;
- a trained readout records the engine it was fitted to (`meta.neural_engine`; readouts older
  than this field were all fitted to the legacy engine) and **runs only on that engine**. The
  controller refuses any other pairing;
- `fly-golf replay --controller` re-runs a record with the engine it names (`controller.model`)
  and, for trained shots, the readout it names (installed, or from `experiments/readouts/archive/`);
- the readout that was installed before this change is archived as
  `experiments/readouts/archive/20260913T200623Z-refit.json`, and a readout trained on
  `fly-golf-lif-v1` replaced it (results in [TRAINING.md](TRAINING.md)).
