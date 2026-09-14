# Motor mapping

Motor control has two stages, and both are engineered:

1. **Neural readout.** Spike counts from documented MaleCNS output populations are turned into
   seven bounded motor channels. This happens in the MaleCNS controller only; the mock produces
   channels directly.
2. **Embodiment decoder.** A fixed transform shared by *every* controller turns the channels into
   a putter stroke: start direction, ball speed and contact.

A third layer is animation. The 3D fly's swing *visualises* the decoded stroke (tempo →
backswing and downswing timing, power → swing arc, aim/face → line). Real flies do not use
muscles to swing putters. The animation is embodiment, not biomechanics.

## Motor channels

`aim_left`, `aim_right`, `stroke_power`, `stroke_tempo`, `face_open`, `face_closed`, `strike`,
all in [0, 1] and validated by `MotorCommand`.

## Stage 1: MaleCNS readout (`brain/malecns/populations.py`, `malecns-motor-v0.1`)

**Chosen a priori, but not provably so.** These populations, windows and constants were written
before the first connectome putt ran and were not selected from observed activity. However, they were
first committed in the same commit as that result (`8c4446b`), so git history **cannot prove** the
ordering. Treat v0.1 as a declared, not verified, pre-registration. Every future change will be
committed before the run that evaluates it.

- **Decision window:** 400 ms of simulated neural time, integrated at 0.1 ms steps.
- **Neural state:** reset to rest before every stroke, so each putt is independently
  reproducible.
- **Readout window:** 150–400 ms. The first 150 ms onset transient is ignored.
- **Bins:** 10 ms.

| Population | Selector (MaleCNS annotations) | n |
| --- | --- | --- |
| `steer_L` / `steer_R` | `type ∈ {DNa01, DNa02}`, soma side L / R | 2 / 2 |
| `DN_L` / `DN_R` | `superclass == descending_neuron`, side L / R | ≈ 650 each |
| `DN_all` | `superclass == descending_neuron` | 1,314 |

Rates are mean spikes per neuron per second over the readout window.

| Channel | Transform | Constant |
| --- | --- | --- |
| `aim_left` | clip((rate(steer_L) − rate(steer_R)) / 50 Hz) | STEER_FULL_HZ = 50 |
| `aim_right` | clip((rate(steer_R) − rate(steer_L)) / 50 Hz) | |
| `stroke_power` | r / (r + 2 Hz), r = rate(DN_all) | POWER_HALF_HZ = 2 |
| `stroke_tempo` | fraction of DN_all readout spikes in the first half of the window (0.5 if none) | |
| `face_closed` | clip((rate(DN_L) − rate(DN_R)) / 2 Hz) | FACE_FULL_HZ = 2 |
| `face_open` | clip((rate(DN_R) − rate(DN_L)) / 2 Hz) | |
| `strike` | clip(DN_all readout spikes / 10) → contact when ≥ 5 spikes | STRIKE_MIN_SPIKES = 5 |

Why these choices:

- **DNa01/DNa02 for aim.** They are established steering descending neurons: ipsilateral
  activity turns the fly (Rayshubskiy *et al.* 2024, *Nature* 631:135). LC10 → AOTU → DNa02 is
  a known male target-tracking route.
- **The whole DN population for power, tempo and face.** A population-level quantity — "how much
  descending drive, how early, which side" — needs no post-hoc choice of single "golf neurons".
  The cost is that it is generic arousal rather than a specific motor program.
- **The strike threshold.** It requires some descending output. A silent brain whiffs, and the
  whiff counts as a stroke.

The named DNs (DNa01, DNa02, DNp09, MDN, DNp20, DNpe017, DNp01, DNb05) are shown in the
technical panel for inspection only. They do not feed the decoder, apart from DNa01/02 through
`steer_*`.

## Stage 2: embodiment decoder (`brain/motor.py`, `motor-mapping-v1`)

- `aim = (aim_left − aim_right) · 25°`, positive = left of the body heading.
- `face = (face_closed − face_open) · 4°`.
- `start direction = body heading + aim + 0.85 · face`. The 0.85 factor is the rule of thumb that
  face angle dominates the start line in putting.
- `smash = 1 − 0.12 · min(1, |tempo − 0.5| / 0.5)`.
- `ball speed = stroke_power · 4.2 m/s · smash` if `strike ≥ 0.5`, else 0 (a whiff).
- Backswing and downswing durations for animation are derived from tempo.

The decoder never sees the cup, the slope or the green speed.

## v0.2: choosing a club (`motor-mapping-v2`, `malecns-motor-v0.2`)

The front nine adds an eighth channel, **`club_reach`** in [0, 1]. The decoder turns it into a
club: `BAG[round(club_reach · 13)]`, evenly spaced slots from the putter (0) to the driver (1).
**The environment never picks a club**, except on the practice green, which hands the fly a
putter (recorded as `forced_club`).

`motor-mapping-v2` decoder:

- **Putter:** exactly `motor-mapping-v1` (same speed, start line and timing).
- **Lofted clubs:** ball speed = club full speed × (0.3 + 0.7 · `stroke_power`) × smash, so
  `stroke_power` is the length of the swing and 0 is a short pitch. Start line = body heading +
  aim + 0.75 · face (the face sets less of the start line than with a putter). Launch angle and
  backspin (scaled with the swing) come from the club; sidespin = 120 rpm per degree of face,
  closed face curving the ball left. Backswing 0.55–1.0 s and downswing 0.2–0.3 s from tempo.
- The decoder still never sees the target, the lie or the green (lie effects are applied by the
  environment; see [COURSE.md](COURSE.md)).

**Fixed readout (`malecns-motor-v0.2`):** the seven v0.1 channels are unchanged, and
`club_reach = r / (r + 6 Hz)` with `r` = DN_all mean rate, i.e. "more descending drive → reach for
a longer club". **Caveat:** the 6 Hz constant was chosen knowing that v0.1's DN_all rate sat at
3.7–10.5 Hz, so it is a priori with respect to golf outcomes but not blind to activity levels.
The expected, and observed, consequence is a nearly constant mid-to-long iron from everywhere,
including the green (see [TRAINING.md](TRAINING.md)).

**Trained readout (`malecns-trained`):** aim, stroke power and club reach can instead come from
linear weights over descending-neuron activity fitted from practice. That controller is labelled
TRAINED everywhere and documented in [TRAINING.md](TRAINING.md).

### Club selection audit (2026-09-13)

- **`club_reach → club` is monotonic and unbiased**: 14 evenly spaced slots, every club reachable,
  interior slots equally wide, and `reach_for(club)` decodes back to the same club (tested in
  `test_engine_selection.py`). Nothing in the decoder favours the 6-iron.
- **The fixed readout's 6-iron comes from the brain side**: `r / (r + 6 Hz)` is monotonic in the
  DN_all rate, but under the proxy injection the rate barely changes between scenes, so the
  channel sits near the middle of the bag. That is a property of this a priori mapping and of
  the connectome's response. It is reported, and **not** patched with a distance rule.
- **The trained readout** chooses with a putter gate and a club head that read only DN-type
  rates. Its club accuracy is reported separately from aim and power (`club_exact_pct`,
  `club_within1_pct` per kind of shot, and club by distance band in `fly-golf bench`).
- **The mock** is the explicitly labelled heuristic baseline: a caddie table, no neurons.
- **Every shot records its club chain** (`club_chain` in the shot record; *Club choice* in the
  BRAIN panel, tagged FIXED READOUT, TRAINED READOUT or MOCK HEURISTIC):

  | Readout | Chain |
  | --- | --- |
  | fixed | sensory channels → MaleCNS dynamics → DN_all rate `r` → `club_reach = r/(r+6)` → club |
  | trained | sensory channels → MaleCNS dynamics → ~480 DN-type rates → putter gate `p(putt)` → (swing) club head raw → calibrated → `club_reach` → club |
  | mock | sensory channels → distance needed → caddie table → `club_reach` → club |


## Motor targets

`SimulationMotorTarget` sends strokes to the deterministic physics. `HardwareMotorTarget` is a
reserved stub: a robotic putter would receive the same `DecodedStroke` and must report a
trajectory back. The loop never needs to know which target executed the stroke.

## First connectome putt (2026-09-13): result

Run `20260913T153252Z-a05678`, seed 7, a 4.5 ft opening putt. It was recorded from the clean commit
`b61c1f9` (physics v2) and replaces an earlier run whose provenance pointed at a commit without the
code. Six strokes, then the fly picked up.

- **Contact:** every stroke made contact, because the DN population produced far more than five
  spikes.
- **Power:** `stroke_power` stayed at 0.65–0.84 whatever the distance, so putts were struck at
  2.5–3.5 m/s. That means huge overshoots on 3–6 ft putts, and near-perfect pace only on the
  30 ft putts (final leaves of 1.0 m and 0.23 m).
- **Aim:** it came out 1–11° left on five strokes and 1° right on one. The steering readout
  (DNa01/02, one neuron per side per type) is left-biased and **does not track the target side**:
  across the 20 MaleCNS strokes recorded so far, only one aimed right. `face_open` varied widely
  (0.39–0.93), because it tracks noise in DN laterality.
- **Where the aim really comes from:** the embodiment addresses the fly within ±10° of the cup
  line (`scenario.py`, `env.py`), so most of the ball's direction comes from where the fly
  stands, **not from neurons**. The neural contribution is the few degrees of decoded offset on
  top of that.
- **Activity and cost:** 17,300–18,800 of 166,700 neurons were active per 400 ms window, with
  101k–371k spikes. Each decision took 1.7–2.2 s of wall time.
- **Reproducibility:** `fly-golf replay 20260913T153252Z-a05678 --controller` reproduces every
  trajectory and every motor channel exactly.

**Interpretation:** the pipeline works end to end, and the fixed network does not putt well.
Descending-population drive under this proxy input sits near saturation and is only weakly
modulated by distance. The proxy LC10 hemifield drive differs by only ~20% between sides at
typical bearings, which is too weak to flip the left-biased steering readout. This result is not
tuned away. Changes to gains or populations must be new, versioned mappings with the same
controls, compared against v0.1, the mock baseline and a shuffled-connectivity control
(`CTRL2-01`).
