# Upstream investigation

Investigated 2026-09-13, before any Fly Golf code was written. Updated the same day, when Fly
Golf's data and neural stack were reimplemented in-house ([DOOMFLY_DECOUPLING_AUDIT.md](DOOMFLY_DECOUPLING_AUDIT.md)): the
"Then" column is what the first versions took, the "Now" column is what remains.

| Repository | Commit inspected | License | Dataset | Use in Fly Golf |
| --- | --- | --- | --- | --- |
| [nftechie/doomfly](https://github.com/nftechie/doomfly) | `71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33` (2026-09-09) | MIT | MaleCNS v1.0 | Historical. The first versions adapted its importer policy, CSR build, LIF kernel and sign proxy and reused its data lock. All are now Fly Golf's own; the adapted kernel is kept only as the legacy engine for replay |
| [vaibhavkedarisetti/fruit-fly-lab](https://github.com/vaibhavkedarisetti/fruit-fly-lab) | `26672e06427c12c61536ce1bd93dae7442944681` (2026-08-28) | **none** | FlyWire FAFB v783 (female) | Architecture and scientific reference only. **No code copied** |

## DOOMFLY: what exists and what we took

DOOMFLY connects the *complete retained* MaleCNS v1.0 graph (166,700 neurons, 25,582,938 edges)
to ViZDoom. The pieces we reviewed:

| DOOMFLY component | File | Then | Now |
| --- | --- | --- | --- |
| Loss-accounted importer: exact uint64 IDs; keeps weak and self edges | `doom/connectome.py` | **Adapted** into `fly_golf/data/prepare.py` (same retention policy, streaming edge indexing) | **Reimplemented** as `data/compiler.py` against the official schema; the retention rule is a documented Fly Golf decision; output byte-identical |
| CSR compile, sign × count × 0.275 mV | `doom/prepare.py` | **Adapted**. Retina, lamina and sugar coupling dropped | **Reimplemented** in `data/compiler.py` |
| Transmitter-sign proxy (ACh +, GABA/Glu/His −, ambiguous +) | `doom/transmitters.py` | **Adapted** (near-verbatim) into `brain/malecns/transmitters.py` | **Reimplemented**; same convention, now stated as Fly Golf's assumption |
| Numba event-driven LIF (dt 0.1 ms, 1.8 ms delay, 2.2 ms refractory) | `doom/engine.py` | **Adapted** into `brain/malecns/engine.py`, adding per-bin counting and explicit reset | **Replaced** by `fly-golf-lif-v1`, written from the Shiu model and exact against Brian2; the adapted kernel is **kept** as `legacy_engine.py` (MIT notice) for replay and older readouts |
| Native C++ lazy kernel with hash-bound binary | `doom/kernel.cpp`, `doom/native.py` | Not used | Not used |
| Retinal projection (R1–R6 → modal L1/L2/L3 column, UV) | `doom/prepare.py` | Not used | Not used; the planned visual path follows the same idea (SENSORY_MAPPING.md) |
| DN readouts (DNa02/DNp09/MDN/MN9 and "BCI" DNp20/DNpe017) | `doom/engine.py` `NeuralControls` | Informed our choice | Unchanged: we read DNa01/02 plus the DN population, and show the named DNs in telemetry |
| Data lock (URLs + SHA-256) | `data-provenance/malecns_v1/source.lock.json` | **Reused** as `data/malecns_v1.lock.json`; digests re-verified locally | **Regenerated** by `fly-golf-data lock` against the official bucket's metadata (same digests) |
| Learning v1–v6 (dopamine-gated KC→MBON plasticity) | `doom_learning*` | Not used | Not used; Fly Golf's trained readout is its own and never changes the connectome |
| Spectator UI, broadcast, checkpoints | `doom-ui`, `doom/server.py` | Not used | Not used |

Lessons carried over:

- DOOMFLY found that its "biological" steering and walking DN readouts were silent under visual
  drive. It chose the working DNp20/DNpe017 readout *after* calibration. We fixed our readout
  populations **before** the first run and recorded them in git (see MOTOR_MAPPING.md).
- DOOMFLY separates live input, modelled propagation and fixed decoding. We keep that separation:
  the controller only sees `SensoryFrame` channels, and the decoder only sees `MotorCommand`
  channels.

## fruit-fly-lab: what we learned

fruit-fly-lab runs the Shiu et al. (2024) LIF model on the **female FlyWire** connectome and ships
an "escape" demo (looming → LC4/LPLC2 → giant fibre). Patterns we adopted *as ideas*:

- a strict simulation/engine separation with a small array interface;
- lesion experiments as a first-class control (planned: `CTRL2-02`);
- SHA-256 provenance tests on every source file;
- honest labelling on screen ("no LLM anywhere").

We did not mix datasets. FlyWire root IDs and cell-type spellings differ from MaleCNS body IDs.
All population selections in Fly Golf use MaleCNS annotations only.

## Other simulators considered

- **Shiu et al. Brian2 reference model (MIT)**: the ancestor of both projects' constants, and now
  the primary specification of Fly Golf's engine. Brian2 itself is used only as a test oracle
  (optional `reference` dependency group): Fly Golf's engine reproduces it spike for spike, and on
  the full graph the adapted DOOMFLY kernel does not (float32 state; see LIF_ENGINE.md).
- **GPU full-connectome simulators**: not investigated in depth, and deliberately deferred. At
  ~2 s of wall time per 400 ms decision window on one CPU core, putting is not compute-bound.
  Correctness and provenance come first.
