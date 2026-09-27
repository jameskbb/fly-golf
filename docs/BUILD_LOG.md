# Build log

## 2026-09-13: initial vertical slice

### Environment

- **Machine:** WSL2 on Linux, 24 cores, 15 GB RAM and an NVIDIA GPU (unused).
- **Installed this session:** uv 0.12.13 and pnpm 12.4.1 (via corepack).
- **Already present:** Node 24, and system Python 3.13; uv provides 3.12 for the project.

### Major decisions

- **Stack:** Python 3.12, FastAPI and Numba on the backend; React, three.js (R3F), zustand and
  zod on the frontend; pnpm and uv workspaces. This is the requested stack, and nothing argued
  against it.
- **Neural code:** adapted **DOOMFLY** (MIT) rather than reinventing it: importer policy, CSR
  build, the Numba LIF kernel and the sign proxy. **fruit-fly-lab** has no license, so it was
  read as a reference only (see UPSTREAM.md).
- **Data source:** the public GCS flat-connectome files. No neuPrint token is needed, and the
  SHA-256 digests match DOOMFLY's lock.
- **Game design:** putting first. The backend runs authoritative 240 Hz physics, the browser only
  plays back 60 Hz trajectories, and the neural state resets at every stroke for reproducible
  shots.
- **Mapping choice:** MaleCNS sensory and motor populations were chosen before the first
  connectome putt: LC10 and JO-C/JO-E for input, DNa01/02 and the DN population for output.
  They were committed together with that result, so git cannot prove the ordering (see the
  review section).
- **Mock:** the MOCK controller sits behind the same protocol, is labelled in code, records and
  UI, and returns no neural statistics.
- **Planning:** development was planned with an AI-assisted planning workflow (GSD). Its
  research, planner and checker agents were **not** available in this session, so phases were
  implemented directly against the roadmap, without plan-checker or verifier gates. The planning
  files stayed in the private incubation repository and are not part of this public repository;
  everything of lasting value from them is in these docs.

### Commands run

- **Setup:** `uv sync`, `pnpm install`.
- **Data:** `uv run fly-golf-data prepare --no-download`. It verified three SHA-256 digests and
  compiled 166,700 neurons and 25,582,938 edges in 8 s.
- **First connectome putt:** `uv run fly-golf putt --controller malecns --seed 7 --traces`, run
  `20260913T145440Z-1133d9`. It was later superseded (see the adversarial review below).
- **Checks:** `uv run pytest` (95 passed, including 4 real-data integration tests),
  `uv run ruff check .` and `ruff format --check`.
- **Frontend checks:** `pnpm -r typecheck`, `pnpm -r test` (8 protocol + 8 web),
  `pnpm --filter @fly-golf/web lint`, and `pnpm --filter @fly-golf/web build`.
- **Live check:** `fly-golf serve` + `vite dev`, driven by headless Chromium (Playwright). It ran
  a mock putt, a controller switch, a MaleCNS putt, and opened the technical panel. Screenshots
  are in `docs/screenshots/`.

### What works (verified by running it)

- **Physics:** deterministic putting physics, with bit-identical replay after a JSON round trip.
- **Headless mock:** a full mock putt through the controller loop, recorded to JSONL.
- **Real-graph putts:** full MaleCNS putts on the real graph. About 9k–19k of 166,700 neurons
  are active per 400 ms decision, taking 1.7–2.9 s of wall time, and the decoded stroke rolls
  the ball.
- **Web app:**
  - the green, flag and cup, and a procedural fly holding a putter that addresses, aims, swings,
    follows through and reacts;
  - the ball follows the backend trajectory with a trail;
  - the brain panel shows spikes, active neurons, per-population rates, the activity sparkline
    and the motor channels;
  - the shot bar and technical panel work, and so do the runs browser and replay;
  - the MOCK and MaleCNS LIVE badges are unambiguous.
- **API and protocol:** version mismatch is rejected over the WebSocket, and the shared protocol
  fixtures validate in both Python and TypeScript.

### What failed or is weak

- **The connectome putts badly.** Descending-neuron population drive saturates `stroke_power`
  at 0.68–0.83 regardless of distance, so short putts are hit 2.6–3.5 m/s and overshoot. Aim
  stays within a few degrees left. This is the honest v0.1 result and was not tuned post hoc.
- **Green speed is not perceived by MaleCNS.** `green_speed` and `ball_at_rest` are not injected
  into the connectome, which matters for pace.
- **Dependency pins.** pnpm resolved React 19.3 and TypeScript 7, above what R3F and
  typescript-eslint allow. They are pinned to React ~19.2 and TypeScript < 6.1.
- **A logged-and-fixed test error.** Two engine unit tests were wrong: the refractory bound, and
  inhibition masked by synchronous firing. The tests were fixed; the kernel was not changed.

### External blockers

None. The data is public, and everything runs locally.

### Next highest-value step

Add the **shuffled-connectivity control** (`CTRL2-01`) and a batch runner that plays N seeded
holes per controller (mock, MaleCNS v0.1, shuffled). Without that comparison, no change to
mappings can be judged. Then consider a versioned `malecns-motor-v0.2`: for example, power from
DNa/DNp subsets relative to a no-input baseline, with the comparison pre-declared.

## 2026-09-13: adversarial review and fixes

After the first push, an independent adversarial reviewer (a Claude Fable agent) audited the repository
at `8c4446b`. It found 4 MAJOR and 8 MINOR issues. All of them were fixed in `b61c1f9`:

- **Provenance (MAJOR).** The first putt's records cited commit `35afc94` with `dirty: false`, but
  that commit contained no code: untracked files were ignored and git state was cached. Now git
  state is evaluated per record, untracked files count as dirty, and `git describe` is stored.
  The headline run was re-recorded from the clean commit `b61c1f9` as
  `20260913T153252Z-a05678`. `fly-golf replay --controller` reproduces every trajectory and every
  motor channel exactly.
- **Pre-registration claim (MAJOR).** The docs and the code docstring now say the v0.1 mappings
  were chosen a priori, but that git history cannot prove it.
- **Lip-out physics (MAJOR).** The lip was applied on cup *entry*, where the ball is always at
  the rim. That made lips negligible (<10 % speed loss), and every holed putt also logged a lip.
  Physics v2 evaluates each pass as a whole, with new tests.
- **UI attribution (MAJOR).** A replayed MaleCNS shot showed the MOCK card when the live session
  was mock. The brain panel and shot bar now describe the shot being shown.
- **Minor fixes:**
  - wrong population counts in SENSORY_MAPPING, now asserted exactly by a test;
  - the aim bias is now disclosed, including that the embodiment supplies most of the aim;
  - empty run directories on every server start;
  - `/api/runs` parsed every shot on the event loop;
  - WebSocket early-disconnect tracebacks, and a misleading `protocol_mismatch` message;
  - engine constants that were decorative;
  - the trail floated on downhill greens;
  - the address-jitter RNG was correlated with the mock's noise RNG;
  - test counts and replay claims in the README.

Things the reviewer tried to break and could not (first review):

- answer leakage into the controller;
- a MaleCNS → mock fallback;
- cross-process determinism;
- JSON round-trip replay;
- the kernel's equivalence with DOOMFLY;
- path traversal;
- concurrent putts;
- CI lockfiles.

## 2026-09-13: front nine, full bag, trained readout

### What was built

- **Course:** `front-nine-v2`, nine hand-designed holes (par 36, 3,352 yd), water on holes 3/4/5/8,
  tree-lined out of bounds, routing targets, penalties, pick-up at par + 5 ([COURSE.md](COURSE.md)).
- **Clubs and physics:** a 14-club bag and `course-physics-v2` (drag + Magnus flight, bounce, surface
  roll, the putting cup rule). `physics.py` (putting v2) is untouched: every v0.1 record, including the
  headline run, still replays trajectories and motor channels exactly.
- **Club choice by the fly:** motor channel `club_reach` (motor-mapping-v2); sensory v0.2 adds long
  range, lie and water cues injected into LC15, leg-bristle and R7d/R8d neurons.
- **Training:** a reservoir-style readout of descending-neuron activity fitted from trial-and-error
  practice, with no-brain and shuffled-connectome controls ([TRAINING.md](TRAINING.md)). The connectome
  is never modified.
- **Web:** 3D holes (fairways, bunkers, animated water, collars, trees), the fly pulling its club from
  a bag, full swings, a follow-cam tracer, scorecard, trained-controller badge.

### Verification

- 141 backend tests (synthetic graph only in CI), 20 web tests, lint, typecheck, build, smoke.
- Headless Chromium runs of the course, a hole jump, the pond hole and the practice green.
- Training and the installed readout were produced from clean commit `164a2d1`.

### Adversarial review (Claude Fable agent, second review)

It found 5 major and 9 minor issues, all fixed in `164a2d1` / `8f091e0`: par-5 routing handed the fly
a 30 m "target" after a drive; the green had a 0.2 m physics step hidden by a render-only collar;
full-shot practice targets were seeded from the true bearing (an analytic shortcut); tee shots were
never held out; the README misdescribed the practice green; plus stroke accounting, deterministic
hole replays, airborne closest approach, camera re-framing, API mode defaults, v0.1 replay on older
graphs, fringe slope. Training was re-run after the fixes; the earlier runs are kept as a pilot.

### What is weak

- The trained readout putts far better than the fixed one (median leave 6.3 m → 1.0 m) but worse than
  a no-brain linear readout of the raw senses. The 1× pilot's shuffled control trained *better* than
  the real wiring; the 3× shuffled control is still to be run.
- Full shots barely improve with training; aim remains the bottleneck.

## 2026-09-13: trained readout v2, round bench, mid-round brain switching (quick task 260913-hjf)

User report: with the trained controller the fly "wants a 5-iron when it should use a wedge",
"grand-slams it into the trees" and had never finished a hole. Asked for better training that still
genuinely uses the connectome, brains switchable mid-round, clearer Mock / MaleCNS / Trained call-outs
and a well-documented training page.

### Diagnosis (measured, not guessed)

- v1's practice targets were degenerate: 88 of 180 held-out full-shot targets were the driver (a soft
  driver and a full wedge finish in the same place; the search kept whichever won by a hair).
- The single `club_reach` regression averaged those targets: 76 of 180 held-out full shots decoded to
  a 6-iron or 5-iron. Putter and lob wedge are neighbours on that axis (26 % of green putts used a
  lob wedge).
- New `fly-golf bench` (complete front-nine rounds, same code path as the app) on the installed v1
  readout, 8 rounds: **79.0 strokes per nine**, 8.3 % of holes holed out, **19.4 trees per round**,
  from 20–60 m it hit 6i/5i/7i/8i and **58 %** of those shots went into the trees.

### What changed

- Practice judges each club robustly and keeps the least club that gets there about as well as the
  best; a `short` situation kind (chips and pitches); readout v2 = putter gate + swing club head +
  putter / swing (aim, power) heads, all linear in DN-type rates; calibration of the decoding by
  practice on training situations; PCA choices fixed to include the full input width (v1 capped the
  14-channel no-brain baseline at 8 directions).
- `POST /api/controller` swaps the brain mid-round; per-hole `controllers`, `controllers_used` in
  state and run.json; scorecard BRAIN row and MIXED BRAINS; runs list MIXED tag.
- Web: "Who is swinging?" brain picker with plain-language category lines, "What's the difference?"
  panel (key M) with the training steps; drawers clear the taller controls.
- docs/TRAINING.md rewritten as the full method page.

### Pilots (scale 1, seed 2, 560 situations; bench = the same 8 round seeds)

| Readout | Strokes / nine | Holes holed out | Trees / round | 20–60 m clubs | Trees from 20–60 m |
| --- | --- | --- | --- | --- | --- |
| v1 installed | 79.0 | 8.3 % | 19.4 | 6i, 5i, 7i, 8i | 58 % |
| v2 pilot | 77.0 | 16.7 % | 12.6 | PW, GW, SW, 9i | 52 % |
| v2 + calibration pilot | 77.5 | 25.0 % | 8.9 | LW 57 %, PW, SW | 32 % |
| Mock (reference) | 36.4 | 100 % | 0 | LW | 0 % |

A larger PCA (up to 392 components) did not help the club head (held-out error 2.2 → 2.3 clubs):
the limit is the information in the DN rates and the amount of practice, not the readout's size.
The LIF engine is deterministic, so training on one seed and playing on others is not a mismatch.

### Adversarial review (Claude Fable agent)

The first attempt stopped on an account spend limit; the rerun found 1 major and 9 minor issues,
all fixed in `bb3e690`. Major: calibration was never compared with the uncalibrated readout, and
the pilots showed it traded full shots for chips behind a pooled score. Fixes: a per-kind
no-regression rule, per-kind practice scores, grid-edge flags, and uncalibrated variants in every
report. Then (`6f3ea6d`) calibration is scored **out of fold**, and `fly-golf refit` re-fits from
saved practice without re-simulating the connectome. Minor: bench provenance (`--attach`), mixed
runs in `fly-golf runs`, crediting a brain only after its stroke, duplicate PCA size, stratified
gate folds, busy messages, test gaps, UI text.

### Final run (scale 6, seed 2, 3,360 situations, 28 min on 12 workers)

- Training `20260913T194711Z` at clean `bb3e690`, refitted out of fold as `20260913T200623Z-refit`
  at clean `6f3ea6d` (**installed**). Held-out: practice putts 5.6 % holed / 0.84 m, green putts
  0 % trees (the untrained readout: 90 %), chips 14.1 m with 8.8 % trees and the club within one
  of the target 88 % of the time, full shots 78 m median (62 m uncalibrated).
- Shuffled-wiring control `20260913T202752Z-shuffled` at clean `6f3ea6d`: **better than the real
  wiring on every kind of shot** (putts 16 % holed, chips 9.7 m, full shots 38 m). The v1 pilot had
  pointed the same way; it is now confirmed at 2.5x the data. The no-brain sensory readout beats both.

| Bench, seeds 100–111 | Strokes / nine | Holes holed out | Trees / round |
| --- | --- | --- | --- |
| Mock | 36.4 | 100 % | 0 |
| MaleCNS untrained | 81.0 | 0 % | 25.3 |
| v1 trained (8 rounds) | 79.0 | 8.3 % | 19.4 |
| v2 uncalibrated | 74.3 | 33.3 % | 11.7 |
| v2 calibrated in-sample | 72.0 | 43.5 % | 7.8 |
| **v2 calibrated out of fold (installed)** | **70.3** | **50.0 %** | **7.0** |

Chosen on seeds 100–111, then confirmed on fresh seeds 200–211: **71.5 per nine** (best 60), **49.1 %
holes holed out**, **5.9 trees per round** (attached to the installed readout's metadata).

### What is weak

- The trained brain is still far worse than the no-brain readout and the mock (36 per nine).
- **Real wiring < shuffled wiring** under this proxy sensory injection: the connectome is not yet an
  advantage. The next scientific step is the sensory mapping, not a bigger readout (392 PCA
  components did not help).
- Calibration still costs held-out full shots (62 m → 78 m median) for its gains around the green.
- Todo captured: plain-language "?" help text on the BRAIN panel.

## 2026-09-13: Fly Golf's own data and neural stack (DOOMFLY decoupling)

Quick task `260913-m8r`. The full audit is [DOOMFLY_DECOUPLING_AUDIT.md](DOOMFLY_DECOUPLING_AUDIT.md).

### What changed

- **Source lock:** `fly-golf-data lock` regenerates `data/malecns_v1.lock.json` against the official
  bucket: size and MD5 must equal the object's `Content-Length` and `x-goog-hash`, SHA-256 is
  computed locally, and the expected counts come from a fresh compile. `fly-golf-data
  verify-source --remote` re-checks the files and the lock (`make verify-source`). Digests
  unchanged; the lock no longer cites DOOMFLY.
- **Compiler:** `data/compiler.py` (`fly-golf-compile-v2`), written against the release schema,
  with the node and edge rules documented as Fly Golf decisions (PROVENANCE.md). It accounts for
  every dropped row and merges duplicates. Output **byte-identical** to the previous compile:
  166,700 neurons, 25,582,938 edges, 124,177,617 contacts.
- **Sign proxy:** `transmitters.py` rewritten (a table, reasons, 33 table-driven tests). The same
  sign for all 166,700 real neurons; 3,718 ambiguous (541 modulator-only, 3,177 unclear or
  missing).
- **Engine:** `fly-golf-lif-v1`, written from the Shiu et al. model specification. It has
  float64 state, Brian2's refractory semantics (checked in Brian2 2.10.1: synapses cannot write
  `g` during refractoriness), an exact propagator and ascending-index event order.
  - **Identical to Brian2**: spike trains in all 16 parity networks, and per-neuron spike counts
    on the full MaleCNS graph in 24 of 24 practice situations.
  - The adapted DOOMFLY kernel matches Brian2 on 15 of 16 small networks but on only 2 of 24
    full-graph situations: float32 state changes about 7,800 neurons' counts per window.
  - 1.15 s per 400 ms window against 1.82 s.
  - The adapted kernel is kept unchanged as `legacy_engine.py`, for replay and for readouts
    fitted to it.
- **Readouts and replay:** readouts record `meta.neural_engine` and only run on that engine.
  The old installed readout and trained readout v1 are archived in `experiments/readouts/archive/`.
  `fly-golf replay --controller` uses the engine and readout each record names; every
  pre-change record tried replays exactly (the V1 headline putt, a v1 trained shot, v2 trained
  shots).
- **Club chain telemetry:** `club_chain` in every shot record and a *Club choice* panel in the
  BRAIN sidebar: senses → DN rate → readout decision (gate probability, club head raw →
  calibrated) → `club_reach` → club, tagged FIXED READOUT, TRAINED READOUT or MOCK HEURISTIC.
  The `club_reach → club` decoder is monotonic, and every club is reachable (tested). The fixed
  readout's 6-iron comes from a DN rate that barely varies, and is reported rather than patched.

### Commands run

- `uv run fly-golf-data lock --write`, `uv run fly-golf-data verify-source --remote`: all ok.
- `uv run fly-golf-data prepare --force --no-download`: `fly-golf-compile-v2`, matches the lock.
- `uv run --group reference python scripts/generate_lif_reference.py`: fixture regenerated.
- Brian2 against both engines on the full graph, 24 situations (script kept out of the repo; the
  integration test `test_full_malecns_graph_matches_brian2` repeats one of them).
- `uv run pytest` (299 passed, integration included), `ruff check`, `ruff format --check`, `pnpm -r
  test / lint / typecheck`, `pnpm --filter @fly-golf/web build`.
- Headless: a mock front nine (35, −1), MaleCNS holes 1–2 on the new engine, and a trained hole.
  `fly-golf replay --controller` on new and pre-change runs: trajectories and motor channels
  identical.
- The app was run (backend + Vite) and driven in headless Chromium: a MaleCNS course shot and a
  trained shot, with no page errors, and the Club choice panel and engine label rendered.

### Retraining on the new engine

From a clean worktree at `091ce01`: `fly-golf train --seed 2 --scale 6 --jobs 12` (24 min) gave
readout `20260913T220118Z` (**installed**). Benches: 70.0 per nine on seeds 100–111 (was 70.3),
71.9 on 200–211 (was 71.5), holes holed out 45–52 %, trees 3–4 per round (was 6–7), and a lob
wedge on 72–82 % of shots from 20–60 m. The untrained MaleCNS readout is still 81.0 (a 6-iron
94 % of the time). The shuffled control on the new engine (`20260913T223205Z-shuffled`) again
beats the real wiring (putts 15.7 % against 6.5 % holed, full shots 37.5 m against 79.2 m). The
engine change needed retraining and changed none of the conclusions
([TRAINING.md](TRAINING.md#engine-migration-2026-09-13)).

## 2026-09-14: readout capacity and side-resolved features

A four-hour training session. Details and tables:
[TRAINING.md](TRAINING.md#readout-capacity-and-side-resolved-features-2026-09-14).

### What changed

- `28b7a06`: training also records every DN type's rate **per soma side** (`features_side` in
  `features.npz`). `fly-golf train/refit --features dn-type-side` fits a readout on them. Readouts
  record `feature_space` (absent means `dn-type`, so every existing readout loads unchanged).
- `109c4a1`: each readout head may use up to 256 PCA components (was 64), still chosen by 5-fold CV
  on the training situations.

### Runs

- `fly-golf refit` of `v3-lif1-seed2-x6` at `109c4a1` gave `20260914T191715Z-refit`: the same practice
  and held-out split as the installed readout, and better on every held-out kind. On bench seeds
  100–111 it scored 66.9 per nine, against 70.0 for the installed readout (reproduced exactly), with
  59 % of holes holed out against 45 %. On fresh seeds 200–211 it scored 66.6, against 71.9, with 70 %
  against 52 %.
- `fly-golf train --seed 3 --scale 12 --jobs 12 --features dn-type-side` at `28b7a06` gave
  `20260914T192725Z`: 6,720 situations, 2,016 held out, 75 min.
- Benched on seeds 100–111 at PCA ≤ 64, the side-resolved readout scored 73.6 per nine, worse
  than the installed readout. Its three refits (side and per-type at PCA ≤ 256, per-type at
  PCA ≤ 64) were still calibrating at the four-hour mark. They were stopped, and no result is
  claimed for them.
- `fly-golf refit` of the shuffled control `20260913T223205Z-shuffled` at `109c4a1` gave
  `20260914T212017Z-shuffled-refit` (109 min). The shuffle still beats the real wiring on every
  held-out kind except the median leave of green putts.
- `8626d54`: `refit` loads the saved practice once. At scale 12 that takes 0.7 s, where the lazy
  NpzFile reads took about 14 minutes.
- **Installed** `20260914T191715Z-refit`, with its seeds 200–211 confirmation attached.
  `20260913T220118Z` is archived, so the published showcase round still replays.

### Provenance notes

- A first scale-12 run on the unchanged `main` was stopped after 10 minutes. The side-resolved run
  saves the per-type features too, so it answered the same question on identical situations.
- One confirmation bench (`v3-type256-s200`) recorded `dirty: true`. Doc edits in its worktree were
  uncommitted while it ran; the code was `109c4a1` unchanged. The confirmation attached to the
  installed readout was re-run from a clean tree.

## 2026-09-14: web demo with ten rounds per brain, and holes mixed at random

### What changed

- The demo draws each hole at random from the brain's recorded rounds (`mixRound`), so reloading
  shows different play. The scorecard's ROUND row names the round each hole came from.
- Round seeds 7–16 were recorded for each brain at `dd1e393` with the new readout and exported: 30
  runs, 31 MB of JSON. They replace the three seed-7 rounds.
- Club heads rest 3 mm behind the ball at address instead of inside it. The iron and wood heads
  had sat 4 mm behind the ball's centre, and the ball's radius is 21 mm.
- The HUD's CLUB cell and the club-choice line show an icon of the chosen club's family.

### Results

Trained 68.5 per nine (57–75), 56 of 90 holes holed; untrained 81 every round; Mock 36.5. The new
readout's seed-7 round is 60; the old readout's was 58. Over ten rounds it averages 68.5.

### Provenance notes

- The first recording of 23 rounds was stamped `dirty`. Subagents' worktrees are created under
  `.claude/worktrees/` inside the checkout, and the recorder counts untracked files as dirty; two
  of the 23 had only their later shots stamped. All 23 were re-recorded from a separate clean
  worktree (`FLY_GOLF_DATA_DIR`/`FLY_GOLF_RUNS_DIR` pointing at the main checkout's data), and
  every re-recording is identical, stroke for stroke.

## 2026-09-17: the fly can see where it is aiming, and breaks 100

### What changed

- **Sensory injection v0.3** (`malecns-sensory-v0.3`). Measured first: under v0.2, a ridge
  regression cannot recover the target's bearing from descending-neuron rates off the green at all
  (R² 0.03 on chips, −0.04 on full shots), because v0.1 multiplies the bearing difference by
  apparent size and `target_distance` saturates past 10 m. v0.3 gives each quantity its own
  population over the full drive range: bearing to LC10a, apparent size to the other LC10 types,
  range to LC15 as a log code, and green speed onto the tarsal drive (v0.2 injected no green-speed
  signal at all). 20 variants were screened on the real connectome before picking this one.
- Readouts record the injection they were fitted under (`meta.malecns_sensory_mapping`) and
  `TrainedReadoutController` pins the controller to it, so readouts fitted before v0.3 keep
  running on the v0.2 drive and older records still replay.
- **Readout `20260917T165536Z` installed**, fitted under v0.3 from 6,720 practice situations.
- The brain soma map gained the four new populations; the web app's brain-firing view lights them.
- The 30 showcase rounds were re-recorded at `43f6d6b` from a clean worktree.

### Results

Bearing recovery goes to 0.71 / 0.54 / 0.78 / 0.80 (putt / green / short / full) and distance to
0.57 / 0.83 / 0.22 / 0.76, with no probe worse than v0.2. Over 36 fresh bench rounds the installed
readout plays **50.5 strokes per nine** against 66.5 for the readout it replaces; holes holed 62 %
→ 97 %, holes picked up 41 per twelve rounds → 1, trees 3.0 a round → 1.3, best round 43. The ten
showcase rounds average **49.3** (42–54), an eighteen-hole pace of 98.6: the fly breaks 100.

### What this does not show

The degree-preserving shuffled-wiring control, trained on the same 6,720 situations under v0.3, is
still better than the real wiring on every held-out kind (putts 0.33 m against 0.54 m). The
no-brain sensory readout still putts far better than either. v0.3 improved how much of the scene
reaches the readout through any wiring; it is not evidence that the MaleCNS connectivity helps.
The control still cannot be compared over complete rounds, because the shuffled graph is built in
memory and thrown away.

### Provenance note: the shas the runs record

The readout was trained, and the thirty showcase rounds were recorded, against commits that were
re-authored before publishing (they carried the wrong committer email, which GitHub rejects). The
trees are byte-identical, so every run still reproduces from the published history; only the sha
in each record differs from the published one:

| recorded in the run | published commit | tree (identical) |
| --- | --- | --- |
| `0db6dcd` (injection v0.3; the readout was trained here) | `16219ad` | `bb322f36` |
| `43f6d6b` (readout installed; the showcase rounds were recorded here) | `04a148d` | `07e2f8da` |
| `4dfc615` (this write-up) | `2871827` | `5aeefbaa` |

`git cat-file -p <published sha>^{tree}` shows the match. Nothing else about the runs changed.

## 2026-09-17: the README's Pond Hop clip, re-shot with the current readout

The README's gameplay clip showed the readout from 2026-09-13 hitting a 4-hybrid into the rough.
It now shows the current readout (`20260917T165536Z`) on the same tee: the tee shot of the web
demo's featured round, seed 7, shot 14. The fly takes a 7-iron, carries the pond and stops 1.43 m
(4.7 ft) from the flag.

How it was captured, so it can be redone:

- `FLY_GOLF_BASE=/ pnpm --filter @fly-golf/web build:showcase`, then `npx vite preview --port 4173`
  in `apps/web`.
- Playwright's Chromium, headless, `--enable-unsafe-swiftshader`, with `DISPLAY`,
  `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` **unset**: under WSLg those make Chromium's GPU process
  hang on the first WebGL context, while 2D canvas and plain script run normally. SwiftShader
  renders the scene at about 14 frames per second, the same rate as the original clip.
- Open `/?run=trained-front-nine-s07&shot=14`, add the style `.showcase-controls{display:none}`
  (the playback panel otherwise covers the fly at address), press `c` to close the scorecard and
  Space to play, and record the page at 1280×720 with `recordVideo`.
- Trim 15.5 s from the moment Space is pressed. MP4: H.264, CRF 26, `+faststart`. GIF: 800×450,
  7 fps, an 80-colour palette with no dithering (4.5 MB; 96 colours and 8 fps looked the same and
  cost 5.3 MB). Playwright's bundled ffmpeg only writes VP8, so the encoding used the static
  ffmpeg from `imageio-ffmpeg`.

Nothing in the app changed for the capture; the shot is the recorded one, bit for bit.

## 2026-09-27: the README's Pond Hop clip, re-shot in cinema mode

Same shot as the entry above (seed 7, shot 14: a 7-iron over the pond to 4.7 ft), filmed again
because the previous clip predates the water rendering fixes and cinema mode. The old clip was a
real-time screen recording at about 14 frames per second with the HUD and brain panel in frame.
The new one has no interface in it and every frame is rendered at an exact playback time.

How it was captured:

- `FLY_GOLF_BASE=/ pnpm --filter @fly-golf/web build:showcase`, then
  `npx vite preview --port 4173 --strictPort` in `apps/web`.
- `social/short-02/tools/capture.mjs --run trained-front-nine-s07 --shot 14 --width 1280
  --height 720 --hold 1.0`, with `DISPLAY`, `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` unset. The
  tool opens the demo with `?cinema=1`, checks that nothing but the stage is visible, and steps a
  virtual clock 1/30 s per frame. No `--frame` crop: the view is the app's own camera.
- MP4: all 15.5 s at 1280x720, 30 fps, H.264, CRF 24, `+faststart` (1.7 MB).
- GIF: the first 13.5 s at 720x405, 10 fps, 112 colours, no dithering (6.9 MB). The palette is
  built from the clip plus enlarged crops of the fly and the flag. A palette built from the clip
  alone, even at 256 colours, drops the red of the eyes, the purple of the vest and the yellow of
  the flag, because they cover too few pixels to be counted.

The profile page (`jameskbb/jameskbb`, `assets/fly-golf.gif`) uses the same GIF.

## 2026-09-27: the back nine, 18 holes, and the first real 18-hole rounds

### What was built

- **The back nine, The Neuropil Nine** (holes 10-18, par 36, 3,479 yd; [COURSE.md](COURSE.md)).
  Each hole is named after a structure of the fly's nervous system or body, shaped to echo it, and
  borrows the strategy of a classic golf hole: a hexagonal pot-bunker cluster, a long Redan-style
  par 3, a double dogleg with a burn crossing twice, a drivable par 4 over church pews, a split
  fairway, an island green, a fan of waste sand, a narrow straight chute and a cape closing hole.
  The names and themes are decoration; nothing about a hole comes from the connectome.
- **A per-hole corridor** (`HoleSpec.corridor_half_width_m`, default 42 m), the only engine
  addition: 30 m on Giant Fiber, 46 m on Mushroom Body, 58 m on Fan-shaped Body.
- **18-hole rounds**: course `eighteen-v1`, par 72, 6,831 yd. `fly-golf round --first/--last`
  (default all 18), `fly-golf bench --nine front|back|both` (default both, `summary.nines`),
  `/api/reset` for holes 1-18, and the exporter for 18-hole rounds.
- **A seed space for holes 10-18**: `10**12 + round_seed * 10 + (hole - 9) + attempt * 10**7`;
  holes 1-9 keep their formula, so they are the same situations as before.
- **The web app**: a theme table (`scene/theme.ts`) that draws the back nine at dusk while the front
  nine stays pixel-identical; an 18-hole scorecard with OUT, IN and TOT; a verdict that names who
  played (the mock is never called the fly) and says whether a full 18 broke 100; showcase mixing
  that draws each hole only from a round that played it.

### Decisions

- **The front nine is frozen.** Its geometry is unchanged bit for bit and a test pins a hash of it,
  so `front-nine-v2` records of holes 1-9 still replay and export.
- **The back nine is held out and nothing was retrained.** Practice situations stay on the front
  nine; the installed readout `20260917T165536Z` plays the back nine without ever having practised
  a shot there, so every back-nine score is a generalisation result.
- **Hole 17 widened from 27 m to 30 m** after an independent review found that its window equalled
  the fly's aiming jitter at address.
- **Hole 13's wording made honest.** "Drivable" describes the geometry: from the tee the pin is
  beyond the 225 m at which the fly targets it, so it is shown the lay-up area; the description no
  longer implies a go-for-it choice.

### Review findings fixed

- **Seed collisions across rounds.** The first back-nine seeds reused the front-nine formula, so
  `hole_seed(7, 11)` equalled `hole_seed(8, 1)`: hole 11 of round 7 replayed hole 1 of round 8's
  randomness. Holes 10-18 now have their own seed space, unique for round seeds 0-999,999 and
  attempts 0-99,999, and a test checks it.
- **Exporting old runs was broken behind a tautological test.** The exporter compared a real
  `front-nine-v2` run's 9-entry scorecard with an 18-entry rebuilt one and refused it; the test
  passed only because it relabelled a new run instead of using real old records. It now compares
  hole by hole over the recorded round's holes, and the test builds its run from committed
  `front-nine-v2` records.

### Results

The thirty showcase rounds were re-recorded as 18-hole rounds (seeds 7-16, clean tree at `6eceef0`)
and replaced the front-nine set; holes 1-9 of each reproduce the old front-nine round stroke for
stroke. The trained fly: 115, 98, 97, 103, 101, 94, 93, 100, 101, 94, mean **99.6** (out 49.3, in
50.3), 176 of 180 holes holed, 5 of 10 under 100. The 18-hole bench of the same readout, 12 rounds
each on seeds 100-111 (`6eceef0`), 200-211 and 300-311 (`bb1770e`): 102.17, 102.0 and 103.58, back
nine 51.83, 50.58 and 53.75 against front 50.33, 51.42 and 49.83 (the front splits reproduce the
earlier front-nine bench), 8 of 36 under 100, best 88, worst 119. In all, 13 of 46 real 18-hole
rounds are under 100 (mean 101.9). The untrained fly scores 162 in every round; the mock, which has
no neurons, averages 73.6.

The "eighteen-hole pace of 98.6" in the 2026-09-17 entry was a front nine doubled. On 18 real
holes the fly breaks 100 sometimes, and on average it does not quite.

### What this does not show

The back nine costs the fly about one to two strokes, so what the readout learnt transfers to
unseen holes almost fully. That is about the sensory injection and the readout, not the wiring: the
shuffled-wiring control and the no-brain baseline have not been run on the back nine, and on the
front nine both beat the real wiring. The dusk look was tuned in a software renderer.

## 2026-09-27: the back nine in the README (yardage book, header, stills)

The course is now 18 holes ([COURSE.md](COURSE.md)), and the README gained an "Around the back
nine" section in the style of the front nine's. How its images were made, since the front-nine
ones were not recorded:

- **Yardage book** (`docs/screenshots/course-hole-10-ommatidia.webp` … `-18-descending-neurons`):
  the real web renderer, the showcase dev server (`vite --mode showcase`) serving a mock 18-hole
  round (round seed 7) through Playwright routes, headless Chromium with SwiftShader WebGL, a
  1440x1000 viewport in cinema mode. A route patch exposed the R3F camera and controls; the camera
  was placed straight above the tee-to-pin line, 0.487 of the way from the tee, high enough (40°
  vertical field of view) that the tee-to-pin distance fills 77 % of the frame height, north up,
  with the scene's distance fog switched off. That framing reproduces the front-nine renders to
  within a few pixels (checked side by side on holes 2, 3 and 8, with matching mean colours), so the
  front-nine renders were most likely made the same way. Hole 15 is framed wider (60 %, centred
  further toward the green) so the whole ring of water and the causeway are in the picture. Each
  frame was downscaled to 1008x700 and saved as WebP quality 72 (20 to 31 kB). The back nine
  renders in its own dusk theme, unchanged.
- **Section header** (`readme-header-back-nine.png`): the existing headers' template rebuilt as
  HTML (1200x160, 2 px accent border, a dark green gradient with faint diagonal lines, a DejaVu
  Sans Mono eyebrow and subtitle, a Liberation Sans Bold title) and rendered by Chromium. Rebuilt
  headers for the front nine and the status section differ from the committed ones by 3 to 4 levels
  per channel on average, mostly in the diagonal lines. The accent is the scorecard's dusk colour,
  `#f0b27a`.
- **Stills** (`back-nine-trained-s07-h15-tee-shot.webp`, `back-nine-trained-s07-h18-approach.webp`):
  the committed recorded round `trained-eighteen-s07` replayed by the showcase dev server in cinema
  mode at 1280x720 (shots 84 and 108), captured 2.0 s and 1.8 s after pressing play. Two stills of a
  mock round were made first and replaced by these before publication.
- **Round-complete screenshot** (`web-demo-round-complete.png`, 1440x900): the committed showcase,
  Trained picked on the splash, a jump to the last stroke of hole 18 of the random mix, played to
  the end. The first mix drawn is the one shown (102).
