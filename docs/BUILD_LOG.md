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
