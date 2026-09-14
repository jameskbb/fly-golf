# Training the fly (a trained readout, not a trained brain)

> **What is trained, and what is not.** The MaleCNS connectome, its synaptic weights and the LIF
> dynamics are never changed. What is learned is a **readout**: weights that turn the firing
> rates of the brain's descending neurons into the stroke: putt or swing, which club, where to aim
> and how hard. This is reservoir-style learning on top of a fixed network. The controller that
> uses it is called `malecns-trained` and is labelled **TRAINED** everywhere (header badge, brain
> picker, scorecard, run records).

This page is the complete description of how the trained readout is made, why it is made that
way, what it achieves and what it does not. Everything here is reproducible from the commands at
the end.

- [The three brains](#the-three-brains)
- [The problem training has to solve](#the-problem-training-has-to-solve)
- [Method (v2, `hindsight-gated-v2`)](#method-v2-hindsight-gated-v2)
- [What went wrong in v1, and what v2 changes](#what-went-wrong-in-v1-and-what-v2-changes)
- [Controls and baselines](#controls-and-baselines)
- [Results](#results)
- [Engine migration (2026-09-13)](#engine-migration-2026-09-13)
- [Honest limits](#honest-limits)
- [Reproduce](#reproduce)

## The three brains

| In the app | Controller id | Stroke comes from | Neural? |
| --- | --- | --- | --- |
| **Mock** (orange) | `mock` | a few lines of hand-written golf rules, like a caddie table | **no** |
| **MaleCNS** (green) | `malecns` | MaleCNS connectome simulation, read out by fixed a-priori rules (`MOTOR_MAPPING.md`) | yes |
| **Trained** (purple) | `malecns-trained` | the same simulation, read out by weights learned from practice (this page) | yes |

The brain can be switched at any moment, even mid-hole (`POST /api/controller`). The next shot is
played by the new brain; every shot record names the brain that played it, each scorecard hole
lists every brain that played a stroke on it, and a round with more than one brain is shown as
**MIXED BRAINS** and never reported as any single brain's score.

## The problem training has to solve

For every shot the same thing happens in play and in training:

```mermaid
flowchart LR
  A[Golf scene] -->|sensory encoder v0.2| B[14 sensory channels]
  B -->|injected into sensory neurons| C[MaleCNS connectome\n166,700 LIF neurons\n400 ms simulated]
  C -->|mean rate of each\ndescending-neuron type\n150-400 ms| D[~481 DN-type rates]
  D -->|READOUT\nthe only learned part| E[putt or swing, club,\naim, power]
  C -->|fixed v0.2 readout| F[tempo, face, strike]
  E & F -->|motor decoder v2| G[club + ball launch]
  G -->|course physics| H[where the ball ends up]
```

The readout sees **only** the descending-neuron (DN) rates: never the distance, the lie, the cup
or any other golf state. If the fly chooses a wedge from 40 m, it is because the activity the
scene evoked in its descending neurons carries that information and the learned weights read it.

## Method (v2, `hindsight-gated-v2`)

Code: `services/sim/src/fly_golf/training/` (`pipeline.py`, `situations.py`) and
`brain/trained.py`.

### 1. Practice situations (`practice-situations-v2`)

A seeded, deterministic set of places to play from. Per `--scale 1`:

| Kind | Count | What |
| --- | --- | --- |
| `putt` | 120 | practice-green putts, 1–6 m (the V1 putting generator) |
| `green` | 120 | putts on the nine course greens, 1–14 m |
| `short` | 120 | **new in v2**: chips and pitches from 3–70 m around the greens (rough, fairway, sand, fringe) |
| `full` | 200 | tee shots and shots along each hole from fairway, rough or sand |

Every situation whose index ends in 1, 4 or 7 (30 %) is **held out**: it is never used for fitting
or for choosing any setting, and all reported results are on those.

### 2. The neural response

For each situation the scene's sensory frame is injected into the connectome exactly as in play,
400 ms of dynamics are simulated from rest, and the feature vector is the mean firing rate of
every DN type in the 150–400 ms readout window. The fixed v0.2 readout's tempo, face and strike are
recorded too (the fly keeps its own untrained tempo and face; only club, aim and power are learned).

### 3. Practice by trial and error (the targets)

The readout needs to know what a good stroke *would have been* from each spot. There is no teacher
and no analytic golf solution: the fly "practises" in the physics simulator.

- **Putts** (green or fringe): a 41 aim × 31 power grid, then an 11 × 11 refinement, all with the
  putter. The grid is smoothed (each cell averaged with its neighbours) before taking the best, so
  the target sits in the middle of a region that works rather than on a lucky edge.
- **Full shots, chips and pitches**: every one of the 14 clubs × 11 swing lengths × 9 aims within
  ±10° of where the fly faces (it addresses its target within ±6°). For each club the grid is
  smoothed the same way, which gives that club's **robust score**: a stroke that only works if it is
  perfect, with the trees or the water a hair away, scores badly because its neighbours do.
  Then the **least club that gets there**: among all clubs whose robust score is within
  max(2 m, 4 % of the distance to the pin) of the best club's, the shortest one is chosen, and its
  aim and swing length are refined.

The score of a stroke is `-(metres from the pin where it stops) - 25 m per penalty stroke`
(holed = +1). Only simulated outcomes are used.

### 4. The readout (`fly-golf-gated-readout-v2`)

All parts read the same input: `z = standardise(log(1 + DN-type rates))`.

```mermaid
flowchart TB
  Z[z = standardised log DN-type rates] --> G{putter gate\nsigmoid of w_g · z + b_g}
  G -->|p ≥ 0.5: putt| P[putter head\naim, power = W_p z + b_p]
  G -->|p < 0.5: swing| C[club head\nclub index = round of w_c · z + b_c\nclipped to lob wedge ... driver]
  C --> S[swing head\naim, power = W_s z + b_s]
```

- **Putter gate**: logistic regression (putt or swing?), fitted by Newton's method.
- **Club head**: ridge regression onto the club's position in the bag (1 = lob wedge … 13 =
  driver), fitted on swing situations only, rounded to the nearest club.
- **Aim / power heads**: two ridge regressions, one on putts and one on swings, because a putter's
  power and a full swing's power mean different things.

Each part is a PCA projection followed by the regression; the number of PCA components (4–64) and
the regularisation are chosen by 5-fold cross-validation on the training situations only, and the
result is collapsed to a single linear layer on `z`. The readout is saved as JSON with full
provenance (git commit, versions, graph, seeds, CV choices, held-out metrics, bench results) and
evaluated exactly as saved.

### 5. Calibration by practice

A regression that is unsure predicts the middle: short shots come out a club or two too long and
long shots too short. On a golf course those errors are not symmetric: a wedge that is a club too
long flies the green into the trees (a penalty stroke, replay from the same spot), a club too short
just leaves another shot. So after the fit the fly practises **with its own readout**: on the
training situations only, it plays the stroke the readout decodes and the physics scores it. Four
numbers about how the outputs are decoded are chosen to maximise that practice score:

- `club_stretch` (1–3): stretches the club head's output about its mean, undoing the shrinkage;
- `club_shift` (−1 to +2.5 clubs): a positive shift takes the shorter club;
- `power_scale` for the putter head and for the swing head (0.8–1.1).

The grid always includes "no change", so calibration can only improve the pooled practice score;
the held-out situations are never used, and the readout still reads nothing but its input vector.

A pooled score can hide a trade-off: in the first pilot the calibration that saved many chips
from the trees made held-out full shots worse (median leave 52 m → 64 m), which only showed up
because the pilot without calibration had been kept. So (review fix) a setting is **only allowed if
no kind of shot (putt, green, short, full) gets more than 1 m worse in practice** than with no
calibration; the practice score before and after is stored **per kind**, settings that land on the
edge of their grid are flagged, and the held-out evaluation always reports the **uncalibrated**
readout next to the calibrated one (`trained_readout_uncalibrated`, `no_brain_uncalibrated`).

### 6. Evaluation

- **Held-out shots**: one stroke per held-out situation, real physics, per kind: holed %, median
  distance left, penalty %, **into the trees %**, and the club chosen compared with the practice
  target (exact, within one club).
- **Complete rounds** (`fly-golf bench`): the fly plays whole front-nine rounds exactly as in the
  app (same session code, sensing, brain, decoder and physics), every shot from wherever the last
  one finished, until it holes out or picks up at par + 5. Reported: strokes per round, holes holed
  out, trees and water per round, and which club it reaches for at each distance.

## What went wrong in v1, and what v2 changes

v1 (`hindsight-ridge-v1`, readout `20260913T172347Z`) is what the user saw "grand-slamming it into
the trees" with a 5-iron from wedge range. Measured on its own training report:

1. **Contradictory targets.** Club and swing length trade off: a soft driver and a full wedge can
   finish in the same place, and v1's practice kept whichever was best by a hair. **88 of 180**
   held-out full-shot targets were the driver, the rest spread over every club.
2. **Regression to the middle of the bag.** One linear regression mapped DN rates to a single
   continuous `club_reach`. With contradictory targets it predicts their average: **76 of 180**
   held-out full shots came out as a 6-iron or 5-iron, usually near full power.
3. **Putter next to the lob wedge.** On the `club_reach` axis the putter (0.00) and the lob wedge
   (0.08) are neighbours, so small errors on the green chose a lob wedge (**26 %** of course-green
   putts).
4. **No short game.** Almost no practice came from 5–60 m, exactly where wedges are needed.
5. **No test of finishing holes.** One stroke per situation never showed that the fly could not
   get round.
6. **A fitting bug** (also fixed): PCA sizes were limited to {4, 8, 16, 32, 64} below the input
   width, so the 14-channel no-brain baseline could only ever use 4 or 8 directions.

v2's answers, in order: the least-club robust target; a gate and a club head instead of one
number; putts and swings on different heads behind a gate; the `short` situations; `fly-golf
bench`; and PCA choices that always include the full width.

## Controls and baselines

Same situations, same held-out split, same fitting code:

| Variant | What it is | What it tells us |
| --- | --- | --- |
| `fixed_v0.2_readout` | the untrained, a-priori readout (the MaleCNS brain in the app) | the starting point |
| `trained_readout` | DN-type rates → v2 readout (fitted, then calibrated by practice) | what training bought |
| `trained_readout_uncalibrated` | the same readout before step 5 | what calibration bought, per kind of shot |
| `no_brain_sensory_readout` | the identical v2 fit on the **14 sensory channels directly**, with a neutral stroke and its own practice targets | how much a readout of the raw senses can do; if the brain version is worse, the network (under this proxy injection) is losing information |
| shuffled connectome (`--control shuffled`) | the whole pipeline on a **degree-preserving shuffle**: each edge keeps its source neuron, sign and synapse count, targets are permuted (in- and out-degrees unchanged) | whether the *specific* MaleCNS wiring matters |
| `mock_heuristic` | the hand-written MOCK controller | a competent non-neural reference |
| `practice_best_upper_bound` | the practice target stroke itself | what a perfect readout could reach with the fly's own tempo and face |

## Results

### The runs

- **Final run** `20260913T194711Z` (`runs/training/v2-final-seed2-x6`), clean commit `bb3e690`:
  `--scale 6 --seed 2`, **3,360 practice situations** (720 practice putts, 720 course-green putts,
  720 chips and pitches, 1,200 full shots; 2.5× the 1,320 behind v1), 1,008 held out. 28 minutes on
  12 workers.
- **Out-of-fold refit** `20260913T200623Z-refit` (`runs/training/v2-final-seed2-x6-oof`), clean
  commit `6f3ea6d`: the same saved practice, re-fitted with the final code (calibration scored
  out of fold), `fly-golf refit`. This is the code at the head of the branch.
- **Shuffled-wiring control** `20260913T202752Z-shuffled` (`runs/training/v2-shuffled-seed2-x6`),
  clean commit `6f3ea6d`: the same pipeline, code and situations on the degree-preserving shuffle
  (every edge keeps its source neuron, sign and synapse count; targets permuted). Its readout is
  refused by `--install`: it is a control, not the fly.
- Pilots at scale 1 (560 situations) are kept in `runs/training/v2-pilot-seed2` and
  `v2cal-pilot-seed2` and summarised in BUILD_LOG.md.

### Held-out shots (one stroke per held-out situation, out-of-fold refit)

Holed %, median distance left, share into the trees, and (for chips and full shots) how often the
club is within one of the practice target's:

| Variant | Practice putts (n=216) | Course-green putts (n=216) | Chips and pitches (n=216) | Full shots (n=360) |
| --- | --- | --- | --- | --- |
| Fixed v0.2 readout (untrained MaleCNS) | 0 %, 5.91 m | 0 %, 6.77 m, **90 % trees** (it chips off the green with irons) | 0 %, 35.3 m, 83 % trees, club ±1 3 % | 0 %, 75.8 m, 19 % trees, club ±1 8 % |
| **Trained v2, calibrated (MaleCNS)** | **5.6 %, 0.84 m** | **3.7 %, 1.29 m, 0 % trees** | **0 %, 14.1 m, 8.8 % trees, club ±1 88 %** | 0 %, 78.2 m, 8.1 % trees, club ±1 55 % |
| Trained v2, uncalibrated | 4.6 %, 0.90 m | 3.2 %, 1.40 m, 0 % | 0 %, 16.9 m, 13.0 % trees, club ±1 62 % | 0 %, **62.0 m**, 5.0 % trees, club ±1 49 % |
| **Shuffled wiring, trained the same way (control)** | **16.2 %, 0.59 m** | **10.6 %, 2.69 m, 0 %** | **0 %, 9.7 m, 0 % trees, club ±1 97 %** | **0.3 %, 37.7 m, 1.4 % trees, club ±1 57 %** |
| No-brain (14 senses, same v2 fit) | 55.6 %, 0.00 m | 54.2 %, 0.00 m, 0 % | 1.9 %, 5.5 m, 0 %, club ±1 97 % | 0 %, 24.4 m, 0 %, club ±1 62 % |
| Mock heuristic | 35.6 %, 0.24 m | 18.5 %, 0.45 m | 0.9 %, 2.4 m | 0.3 %, 18.7 m |
| Practice best (upper bound) | 100 %, 0 m | 100 %, 0 m | 17 %, 0.49 m | 3.9 %, 6.7 m |

For comparison, v1 on its own (different) held-out set: practice putts 6.5 % / 1.01 m, green putts
2.8 % / 1.86 m with 4.6 % penalties, full shots 76.4 m with 16 % penalties, and no chips measured.

### Complete front-nine rounds (`fly-golf bench`, same round seeds 100–111)

| Brain | Rounds | Strokes per nine (par 36) | Holes holed out | Trees per round | Clubs from 20–60 m | Trees from 20–60 m |
| --- | --- | --- | --- | --- | --- | --- |
| Mock (hand-written, no brain) | 12 | 36.4 | 100 % | 0 | lob wedge | 0 % |
| MaleCNS, untrained readout | 12 | 81.0 (every hole picked up) | 0 % | 25.3 | 6-iron 94 % | 69 % |
| Trained **v1** (the one you played) | 8 | 79.0 | 8.3 % | 19.4 | 6i, 5i, 7i, 8i | 58 % |
| Trained v2, uncalibrated | 12 | 74.3 | 33.3 % | 11.7 | GW, PW, LW, SW | 48 % |
| Trained v2, calibrated (in-sample, `bb3e690`) | 12 | 72.0 | 43.5 % | 7.8 | **lob wedge 64 %** | 21 % |
| **Trained v2, calibrated out of fold (`6f3ea6d`, installed)** | 12 | **70.3** (best 61) | **50.0 %** | **7.0** | **lob wedge 65 %** | **17 %** |

A hole is "picked up" at par + 5 (docs/COURSE.md), so a nine can never exceed 81 strokes.

**Confirmation on fresh rounds.** The readout to install was chosen on seeds 100–111 above; to keep
that choice from flattering it, it was then played on 12 rounds it had never been chosen on (seeds
200–211): **71.5 strokes per nine** (best 60), **49.1 % of holes holed out**, **5.9 trees per
round**, lob wedge on 66 % of shots from 20–60 m. The selection did not flatter it. This summary is
stored in the installed readout's metadata (`meta.bench`, via `fly-golf bench --attach`) and shown
in the app's "What's the difference?" panel.

### What this says, honestly

- **The reported failure is fixed.** From 20–60 m v1 hit a 6-, 5- or 7-iron and 58 % of those shots
  went into the trees; v2 reaches for a lob wedge and far fewer chips leave the course (17 %). Trees
  per round fell from 19 to 7 and the fly now holes out on half of its holes instead of 1 in 12.
- **Putting from the course greens stopped being a disaster.** The untrained readout chips off the
  green with an iron 90 % of the time; the gate sends every green shot to the putter.
- **Calibration is a trade, and it is reported as one.** It makes chips much better and the median
  full shot worse (62 m → 78 m held out); in complete rounds the chips win (more holes finished,
  fewer trees), which is why a calibrated readout is the one installed: the out-of-fold refit
  `20260913T200623Z-refit`, which beat the in-sample calibration on the same rounds.
- **The brain is still the bottleneck.** The same fit on the 14 raw sensory channels putts 10×
  better and leaves full shots at 24 m instead of 78 m, and the hand-written mock goes round in
  36. Under this proxy injection the connectome's descending neurons carry the scene much less
  clearly than the senses that went in: even on its own training data the club head is off by
  about two clubs on average, and a bigger readout (up to 392 components) did not help.
- **The real wiring does not help; on this test it hurts.** The degree-preserving shuffle, trained
  on the same situations with the same code, beats the real MaleCNS connectome on every kind of
  shot: 16 % of practice putts holed against 6 %, chips 9.7 m against 14.1 m, full shots 38 m
  against 78 m, and its club head is off by 1.1 clubs on its training data against 2.0. The 1×
  pilot of v1 showed the same direction. So, under this proxy sensory injection and this
  descending-neuron readout, the reconstructed wiring passes the golf scene to the output layer
  *less usably* than random wiring with the same degrees. This is a real, reproducible result
  about this model, not about flies, and it is reported rather than hidden. (Caveat: each graph's
  targets are practised with its own untrained tempo / face / strike, so their ceilings differ;
  see each report's upper-bound row, e.g. 72 % vs 100 % of green putts. That does not explain a
  2× gap in full shots.) What the installed readout does is genuinely read the real connectome's
  activity, as the app claims; what this result says is that the real connectome is not yet an
  advantage.

## Engine migration (2026-09-13)

The neural engine changed from the DOOMFLY-adapted `lif-doomfly-r2-adapted-v1` (float32) to Fly
Golf's own `fly-golf-lif-v1`, which reproduces the Brian2 reference spike for spike on the full
graph ([LIF_ENGINE.md](LIF_ENGINE.md)). The two engines' descending-neuron features correlate at
only 0.84–0.99 per situation, so **a readout fitted to one engine is not valid on the other**:

- every readout records `meta.neural_engine` and runs only on that engine (readouts without the
  field predate it and were fitted to the legacy engine);
- the previously installed readout `20260913T200623Z-refit` and trained readout v1
  `20260913T172347Z` are archived in `experiments/readouts/archive/`, where old records find them
  for replay;
- the whole pipeline was re-run on the new engine with the same code, situations and seed from a
  clean checkout (`091ce01`): readout **`20260913T220118Z`** (`runs/training/v3-lif1-seed2-x6`,
  24 min on 12 workers), now **installed**, and the shuffled-wiring control
  `20260913T223205Z-shuffled` (`runs/training/v3-lif1-shuffled-seed2-x6`).

Held-out shots (the same 1,008 held-out situations):

| Variant | Engine | Practice putts | Course-green putts | Chips and pitches | Full shots |
| --- | --- | --- | --- | --- | --- |
| Fixed v0.2 readout | legacy | 0 %, 5.91 m | 0 %, 6.77 m, 90 % trees | 0 %, 35.3 m, 83 % trees | 0 %, 75.8 m, 19 % trees |
| Fixed v0.2 readout | **fly-golf-lif-v1** | 0 %, 6.04 m | 0 %, 6.77 m, 90 % trees | 0 %, 35.3 m, 82 % trees | 0 %, 73.0 m, 19 % trees |
| Trained, calibrated | legacy (`…200623Z-refit`) | 5.6 %, 0.84 m | 3.7 %, 1.29 m | 0 %, 14.1 m, 8.8 % trees, club ±1 88 % | 0 %, 78.2 m, 8.1 % trees, club ±1 55 % |
| Trained, calibrated | **fly-golf-lif-v1** (`20260913T220118Z`) | **6.5 %, 0.82 m** | 3.2 %, 1.28 m | 0 %, 14.0 m, **4.6 % trees, club ±1 91 %** | 0 %, 79.2 m, 6.1 % trees, club ±1 55 % |
| Trained, uncalibrated | legacy | 4.6 %, 0.90 m | 3.2 %, 1.40 m | 0 %, 16.9 m, 13 % trees | 0 %, 62.0 m, 5.0 % trees |
| Trained, uncalibrated | fly-golf-lif-v1 | 6.9 %, 0.94 m | 2.8 %, 1.36 m | 0 %, 16.7 m, 14 % trees | 0 %, **80.0 m**, 7.5 % trees |
| Shuffled wiring (control) | legacy | 16.2 %, 0.59 m | 10.6 %, 2.69 m | 0 %, 9.7 m | 0.3 %, 37.7 m |
| Shuffled wiring (control) | fly-golf-lif-v1 | 15.7 %, 0.49 m | 11.1 %, 2.46 m | 0 %, 10.2 m | 0 %, 37.5 m |
| No-brain / mock | (no neurons) | unchanged | | | |

Complete front-nine rounds (`fly-golf bench`, 12 rounds each):

| Brain | Engine | Seeds | Strokes / nine | Holes holed out | Trees / round | 20–60 m |
| --- | --- | --- | --- | --- | --- | --- |
| MaleCNS, untrained | legacy | 100–111 | 81.0 | 0 % | 25.3 | 6-iron 94 % |
| MaleCNS, untrained | fly-golf-lif-v1 | 100–111 | 81.0 | 0 % | 23.8 | 6-iron 94 % |
| Trained (installed before) | legacy | 100–111 | 70.3 | 50.0 % | 7.0 | lob wedge 65 %, 17 % trees |
| **Trained (installed now)** | **fly-golf-lif-v1** | 100–111 | **70.0** (best 64) | 45.4 % | **3.3** | lob wedge 82 %, 9.6 % trees |
| Trained (installed before) | legacy | 200–211 | 71.5 | 49.1 % | 5.9 | lob wedge 66 %, 21 % trees |
| **Trained (installed now)** | **fly-golf-lif-v1** | 200–211 | **71.9** (best 58) | **51.9 %** | 4.0 | lob wedge 72 %, 14 % trees |

What the migration says:

- **Retraining was necessary and sufficient.** On the new engine the same pipeline gives a readout
  of the same quality: strokes per nine within half a stroke on both seed sets, holes holed out
  45–52 % against 49–50 %, and fewer trees (3–4 per round against 6–7). Putting and chipping are
  unchanged within noise. No result depended on the legacy engine's float32 rounding.
- **The uncalibrated full-shot number moved** (62 m → 80 m median). Calibration now picks a
  larger shift toward shorter clubs (stretch 1.5, shift 1.5; was 1.75, 1.0), and the calibrated
  readouts agree (78 m and 79 m). This is one reason the no-regression calibration rule and the
  uncalibrated row are kept in every report.
- **The central finding is unchanged.** On the Brian2-exact engine the degree-preserving shuffle
  still trains better than the real MaleCNS wiring on every kind of shot (putts 15.7 % against
  6.5 % holed, full shots 37.5 m against 79.2 m). The no-brain readout of the raw senses still
  beats both.

## Honest limits

- **It is a readout, not learning in the brain.** Synapses are fixed. The claim is only that the
  DN activity evoked by the scene carries information a linear readout can use.
- **Proxy sensing.** The scene reaches the connectome through a documented proxy injection
  (`SENSORY_MAPPING.md`), not a model of the fly's eyes.
- **Practice uses a simulator the fly does not have.** The targets come from trying strokes in the
  physics engine: hindsight, not foresight. At play time nothing but DN activity reaches the
  readout.
- **The no-brain baseline and the shuffled control are the real tests.** Until the connectome
  version beats a readout of the raw senses and a randomly rewired brain, no claim is made that
  the MaleCNS wiring itself helps the fly play golf.

## Reproduce

```sh
SIM="uv --directory services/sim run fly-golf"
make data                                                     # the connectome (once)
$SIM train --seed 2 --scale 6 --jobs 12 --out runs/training/v2-final-seed2-x6          # ~28 min
$SIM refit runs/training/v2-final-seed2-x6 --out runs/training/v2-final-seed2-x6-oof   # no brain simulation
$SIM train --seed 2 --scale 6 --jobs 12 --control shuffled --out runs/training/v2-shuffled-seed2-x6
# choose on seeds 100-111, then confirm on fresh seeds 200-211 and record it in the readout:
$SIM bench --controller malecns-trained --readout runs/training/v2-final-seed2-x6-oof/readout.json --rounds 12 --seed 100
$SIM bench --controller malecns-trained --readout <chosen>/readout.json --rounds 12 --seed 200 --attach
$SIM bench --controller malecns --rounds 12 --seed 100
$SIM bench --controller mock --rounds 12 --seed 100
```

`fly-golf refit` re-fits, re-calibrates and re-evaluates from a run's saved practice
(`features.npz` holds the neural features, targets, sensory channels and the fly's own fixed
tempo / face / strike), so fitting code can be improved without re-simulating the connectome; the
new report records the run it was refitted from. Run training from a clean checkout (the readout
records the commit and whether the tree was dirty). Run one full-graph process at a time (15 GB
machine). Each training run writes
`runs/training/<name>/report.json` (every situation, CV tables, all metrics), `readout.json`,
`no_brain_readout.json` and `features.npz`; each bench writes `runs/bench/<controller>-<utc>.json`
with every shot of every round. The installed readout is
`experiments/readouts/malecns-readout-v1.json` (the file name is historical; the `format` field
inside says v1 or v2) and records the commit it was trained at and its neural engine
(`meta.neural_engine`). Since the engine migration the installed readout is `20260913T220118Z`,
trained on `fly-golf-lif-v1` with the commands above (`--out runs/training/v3-lif1-seed2-x6`, then
the two benches, `--attach` on seeds 200–211).
