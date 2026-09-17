# Sensory mapping

> **Status:** V0 **proxy** encoder. The fly does *not* see the green through modelled eyes yet.
> Engineered channels summarise the golf state, and those channels are injected as constant
> current into selected MaleCNS sensory populations.

## Stage 1: golf state → proxy channels (`fly_golf/brain/sensory.py`, `proxy-sensory-v0.1`)

The encoder receives the true physical observation. It outputs nine bounded channels in [0, 1].
It **never** outputs a solution: there is no aim angle, no stroke power and no cup coordinates.

| Channel | Definition | Full scale |
| --- | --- | --- |
| `target_left` | cup bearing to the fly's left of its body heading | 45° |
| `target_right` | cup bearing to the fly's right | 45° |
| `target_distance` | distance ball → cup | 10 m |
| `slope_uphill` | rise per metre along the ball → cup line (uphill putt) | 3 % |
| `slope_downhill` | fall per metre along the line (downhill putt) | 3 % |
| `slope_fall_left` | ground falls to the left of the line (ball breaks left) | 3 % |
| `slope_fall_right` | ground falls to the right of the line | 3 % |
| `green_speed` | (stimp − 6) / 8 | stimp 14 |
| `ball_at_rest` | 1 if the ball is stationary | — |

Values are clipped to [0, 1]. Malformed input (NaN, wrong keys, out-of-range values or non-numbers)
is rejected by `SensoryFrame` validation, and tests cover it. The body heading at address is
jittered ±10° from the cup line by the seeded scenario. That means "which way to aim" is a
genuine perceptual quantity rather than a constant.

## Stage 2: channels → MaleCNS populations (`fly_golf/brain/malecns/populations.py`, `malecns-sensory-v0.1`)

Each population receives a constant drive (mV-equivalent, identical for every neuron in the
population) for the whole 400 ms decision window. The maximum drive is I_max = 30 mV (a Fly Golf
choice; the value was first taken from the photoreceptor saturation used by DOOMFLY).

| Population | MaleCNS selector | n neurons | Drive |
| --- | --- | --- | --- |
| `LC10_L` | `type` starts with `LC10`, side L | 479 | I_max · size · w_left |
| `LC10_R` | `type` starts with `LC10`, side R | 481 | I_max · size · (1 − w_left) |
| `JO-C_L` / `JO-C_R` | `type` starts with `JO-C`, side L/R | 46 / 22 | I_max · clip(0.6 · uphill + 0.8 · fall_side) |
| `JO-E_L` / `JO-E_R` | `type` starts with `JO-E`, side L/R | 157 / 110 | I_max · clip(0.6 · downhill + 0.8 · fall_side) |

where `size = 0.4 + 0.6 · (1 − target_distance)` (a nearer target looks bigger) and
`w_left = 0.5 + 0.5 · (target_left − target_right)`.

Population sizes are from the compiled v1.0 graph, and the integration test
`test_real_populations_resolve` asserts them exactly.

**Side conventions:**

- `side` is `somaSide`, falling back to `rootSide` when the soma side is missing.
- All 672 Johnston's organ cells have no soma side (their cell bodies are in the antenna), so their
  side comes from `rootSide`.
- The `LC10` prefix also matches 11 `LC10_unclear` cells.
- 10 descending neurons are annotated side `M`. They count in `DN_all`, but in neither `DN_L` nor
  `DN_R`.

### Why these populations

- **LC10:** lobula columnar visual projection neurons. In males, LC10a is required for tracking
  a moving visual target during courtship (Ribeiro *et al.* 2018, *Cell* 174:607; Hindmarsh
  Sten *et al.* 2021, *Nature* 593:548). LC10 cells in each optic lobe mainly sample the
  ipsilateral visual field. So "target to the left" becomes more drive to the left LC10
  population. This is the closest well-characterised "attend to an object in the field" input
  in the male CNS, and it has a known path toward steering (LC10 → AOTU → DNa02).
- **JO-C / JO-E:** Johnston's organ neurons respond to sustained antennal deflection. They carry
  gravity and wind signals, not sound (Kamikouchi *et al.* 2009, *Nature* 458:165). They are a
  plausible proxy for "which way is the ground tilted".

### Known limitations (do not over-interpret)

- **Hemifield drive, not vision.** No image is formed. All LC10 cells on one side receive the same
  current regardless of their receptive fields.
- **Johnston's organ senses antennal deflection, not the tilt of the green under the ball.** The
  mapping is an analogy.
- **`green_speed` and `ball_at_rest` are not injected** into MaleCNS in V0. The MaleCNS controller
  therefore cannot perceive green speed. The MOCK controller can.
- **Constant current into sensory neurons that are graded in vivo** is a modelling convenience
  (other whole-connectome simulations, DOOMFLY's retina among them, make the same one).
- **Selection is a judgement call.** Different populations are valid experiments, and must bump
  `MALECNS_SENSORY_MAPPING_VERSION`.

## v0.2: the whole course (`proxy-sensory-v0.2`, `malecns-sensory-v0.2`)

For the front nine the encoder emits **14** channels: the nine above, computed with the same
formulas, plus five new ones. On the course the "target" is the fly's aiming point (the next
routing point, or the pin once within 225 m; see [COURSE.md](COURSE.md)). Records keep the
version, and `SensoryFrame` validates the channel set that version defines, so v0.1 records
still replay.

| Channel | Definition | Full scale |
| --- | --- | --- |
| `target_far` | distance ball → target | 250 m |
| `lie_green` | 1 on the green or fringe | — |
| `lie_rough` | 1 in the rough | — |
| `lie_sand` | 1 in a bunker | — |
| `water_on_line` | fraction of the straight ball → target line over water | 1 |

(Tee and fairway are the case where all three lie flags are 0.)

**Injection** (`malecns-sensory-v0.2`). The nine shared channels drive the same populations with
the same formulas as v0.1. Three populations are added, chosen before any v0.2 run:

| Population | MaleCNS selector | n neurons | Drive |
| --- | --- | --- | --- |
| `LC15` | `type` starts with `LC15`, both sides | 126 | I_max · target_far |
| `leg_bristle` | `superclass == vnc_sensory`, `subclass == leg bristle` | 688 | I_max · roughness(lie): green 0.15, tee/fairway 0.45, rough 0.8, sand 1.0 |
| `R7d_R8d` | `type ∈ {R7d, R8d}` | 158 | I_max · water_on_line |

Why these, and what they are not:

- **LC15** is another lobula columnar visual projection type (it responds to moving bars and
  small objects). It is a stand-in for "the target is far away"; it is not a distance detector,
  and flies do not judge 200 m.
- **Leg bristle neurons** are tactile mechanosensors on the legs, a reasonable proxy for "what
  the ground under the feet feels like". The roughness scale is ours.
- **R7d/R8d** are the dorsal-rim polarization photoreceptors. Insects detect water partly by
  the polarized glint of its surface (in *Drosophila*, via ventral R7/R8; Wernet *et al.* 2012,
  *Curr. Biol.* 22:12), so the dorsal-rim cells are a labelled stand-in, not the pathway a fly
  would use.
- As in v0.1, `green_speed` and `ball_at_rest` are not injected; the MaleCNS controller still
  cannot perceive green speed.

The integration test `test_real_populations_resolve` asserts every population size.

## v0.3: one quantity per population (`malecns-sensory-v0.3`)

The channels (`proxy-sensory-v0.2`) are unchanged. What changed is **stage 2**, how they are
injected — and only because we measured how little of them survived.

### What we measured

For 840 practice situations we injected the v0.2 drive, simulated the 400 ms decision window, and
asked how much of each scene quantity a ridge regression can recover from the descending-neuron
type rates the readout actually sees (PCA size and regularisation chosen inside the training
split, R² on held-out situations):

| recovered from DN rates | putt | green | short | full |
| --- | --- | --- | --- | --- |
| target bearing (`target_left − target_right`) | 0.30 | 0.17 | 0.03 | −0.04 |
| distance to target (log) | 0.15 | 0.72 | 0.02 | 0.61 |
| green speed | −0.08 | 0.05 | −0.06 | 0.02 |

Off the green the fly could not perceive which way its target lay **at all**, and on the practice
green it could barely perceive how far away the hole was. Two causes, both in the formulas:

1. **Bearing was multiplied by apparent size.** v0.1 sets `LC10_L = I_max · size · w_left`, so the
   left–right difference that carries bearing scales with `size`. Off the green `target_distance`
   (full scale 10 m) saturates, `size` sits at its 0.4 floor, and — because the bearing channels
   are full scale at 45° while the fly addresses its target within about ±6° — the whole spread of
   real bearings became a drive difference with a standard deviation under 1 mV out of 30.
2. **Distance had one code with the wrong range.** `target_distance` saturates past 10 m and
   `target_far` (full scale 250 m) is under 0.3 for every shot inside 70 m, so between 10 m and
   70 m almost nothing varied.

And green speed was never injected at all, while stroke power on a putt depends on it.

### What v0.3 does

Each quantity gets its own population over the full drive range, and nothing is multiplied by
anything else.

| Population | MaleCNS selector | n neurons | Drive |
| --- | --- | --- | --- |
| `LC10a_L` / `LC10a_R` | `type` starts with `LC10a`, side L/R | 135 / 140 | I_max · w_left / I_max · (1 − w_left) |
| `LC10rest_L` / `LC10rest_R` | other `LC10` types, side L/R | 344 / 341 | I_max · size (both sides alike) |
| `LC15` | unchanged | 126 | I_max · range(d) |
| `leg_bristle` | unchanged | 688 | I_max · roughness(lie), **on a green** 0.30 − 0.20 · `green_speed` |

where, with `d = 250 · target_far` metres,

- `w_left = clip(0.5 + 0.5 · BEARING_GAIN · (target_left − target_right))`, `BEARING_GAIN = 8`
- `size = 0.4 + 0.6 · (1 − target_distance)` — the v0.1 formula, now on its own populations
- `range(d) = clip(log1p(d / 0.5) / log1p(500))` — a log (Weber–Fechner) distance code, which
  resolves a 2 m putt and a 4 m putt and still climbs between 150 m and 250 m

The JO-C / JO-E slope drives and the R7d/R8d water drive are v0.2's, unchanged. `LC10_L` /
`LC10_R` still resolve and still carry the v0.1 and v0.2 formulas, so older records replay.

### Why these populations

- **LC10a** is the LC10 subtype required for tracking a visual target during male courtship
  (Ribeiro *et al.* 2018, *Cell* 174:607; Hindmarsh Sten *et al.* 2021, *Nature* 593:548). If any
  cells in this connectome are going to say "the thing I am after is over there", these are the
  labelled candidates, so bearing goes to them alone.
- **LC10b/c/d/e** keep the apparent-size drive. They are still LC10, still ipsilateral, and the
  split is a modelling choice, not a claim that these types encode size in a fly.
- **Green speed on the leg bristles** extends the existing tarsal-contact proxy: a faster green is
  a smoother surface under the feet. It is an analogy in exactly the way the roughness scale
  already was.

### What it bought

Same measurement, same situations, v0.3 injection:

| recovered from DN rates | putt | green | short | full |
| --- | --- | --- | --- | --- |
| target bearing | 0.71 | 0.54 | 0.78 | 0.80 |
| distance to target (log) | 0.57 | 0.83 | 0.22 | 0.76 |
| green speed | 0.20 | −0.01 | −0.03 | 0.01 |

No probe is worse than under v0.2, and the slope probes are unchanged within noise. Distance for
chips and pitches (`short`, 0.22) is still the weakest link.

### Honesty notes

- This is still **not vision**. No image is formed; LC10a cells on one side all receive the same
  current whatever their receptive fields.
- Nothing here encodes a solution. The fly is told where its target is and how the ground feels,
  never which club, aim or power to use — the same rule v0.1 set.
- Changing the injection changes what every readout sees, so a readout records the mapping it was
  fitted under (`meta.malecns_sensory_mapping`) and `TrainedReadoutController` pins the controller
  to it. Readouts fitted before v0.3 are assumed to be v0.2 and keep running on the v0.2 drive.
- The gains (8, the 0.5 m / 500 m log constants, the green-speed scale) were chosen by the
  screening measurement above, on practice situations drawn with a seed used for nothing else,
  before any round was played with them.


## V1 roadmap: modelled vision

This is designed but not built (`SENS2-01`):

1. Render a compact fly-eye view of the 3D green from the fly's head, on the backend and
   deterministically.
2. Sample luminance at the 3,335 mapped R1–R6 photoreceptor UV positions, from a modal-column
   projection (R1–R6 → L1/L2/L3 hexes) that Fly Golf would compute itself from the MaleCNS
   annotations; DOOMFLY showed the approach works.
3. Drive photoreceptors with a low-pass saturating current, plus lamina tonic drive.
4. Remove `target_*` proxy channels once visual input reaches LC10 through the modelled optic
   lobe.

The `SensoryEncoder` → `SensoryFrame` interface stays the same. A visual encoder would add a
second, larger frame type, which the MaleCNS controller would consume directly.
