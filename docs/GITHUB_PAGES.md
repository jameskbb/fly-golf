# The web demo (GitHub Pages)

**URL:** https://jameskbb.github.io/fly-golf/

The web demo is Fly Golf's **Showcase Mode**: the real 3D app replaying Fly Golf rounds that were
recorded with the full simulator. It runs entirely in the browser. There is no backend, and
nothing is simulated on the page: the neural simulation, the club choice, the swing and the ball
flight were all computed beforehand and stored as shot records. How the two modes fit together
is in [ARCHITECTURE.md](ARCHITECTURE.md).

## One-time repository setting

GitHub does not let a workflow switch Pages on by itself. Once, in the repository:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

Until this is set, the `Pages` workflow fails at `actions/configure-pages` with a "Get Pages site
failed" (Not Found) error. After setting it, re-run the workflow from the Actions tab, or push to
`main`.

## Deployment workflow

`.github/workflows/pages.yml` runs on every push to `main` and on manual dispatch:

1. checks out the repository and installs Node 22 and pnpm from the lockfile;
2. lints, typechecks and runs the frontend and protocol tests. These tests validate the committed
   showcase files against the shared schemas and check the rebuilt scorecards;
3. builds the app in showcase mode (`pnpm --filter @fly-golf/web build:showcase`, base path
   `/fly-golf/`);
4. uploads `apps/web/dist` with `actions/upload-pages-artifact` and deploys it with
   `actions/deploy-pages` to the `github-pages` environment.

The Python simulation never runs in this workflow. The showcase JSON is exported locally and
committed.

## Preview locally

No backend is needed:

```sh
pnpm install
pnpm showcase             # dev server:   http://localhost:5173/fly-golf/
pnpm build:showcase       # the Pages build, into apps/web/dist
pnpm preview              # serve it:     http://localhost:4173/fly-golf/
```

`make showcase`, `make build-showcase` and `make preview-showcase` do the same. Both servers use the
`/fly-golf/` base path, so what you see locally is what Pages serves. To build for another base
path, for example a fork or a custom domain, set `FLY_GOLF_BASE=/your-path/` when building. Normal
live development (`make dev`, http://localhost:5173/) is unchanged.

## Export a new showcase run

Showcase runs must be real, complete records. Record a round with the simulator (the connectome
must be compiled: `make data`), then export it:

```sh
# 1. Record. Commit first: every record stores the git commit and whether the tree was dirty.
#    A round is all 18 holes unless you pass --first / --last.
uv --directory services/sim run fly-golf round --controller malecns-trained --seed 7
#    -> recorded run: runs/<run_id>

# 2. Export into apps/web/public/showcase/ (validates every shot; never modifies the run).
uv --directory services/sim run fly-golf export-showcase <run_id> \
  --slug trained-eighteen-s07 \
  --title "Trained MaleCNS - Eighteen, round 7" \
  --description "One or two honest sentences about what this run is."

# 3. Check, then commit the JSON.
pnpm -r test && uv --directory services/sim run pytest tests/test_showcase_export.py
```

The exporter prints the file size and any notes, for example on shots from abandoned attempts
that were left out, a dirty working tree, or removed local paths. It refuses to export:

- a run that fails `ShotRecord` validation, or practice-green runs (the showcase shows the course);
- a round recorded on a course version whose holes differ from the current code's (`eighteen-v1`).
  Records of holes 1-9 made under `front-nine-v2` are still accepted, because those holes are
  unchanged bit for bit; the export then records `front-nine-v2` as the run's course version;
- a MaleCNS shot without recorded neural activity;
- a run containing MOCK shots under a title that claims MaleCNS or the connectome.

Use `--round <seed>` when a run holds several rounds. `--out` writes somewhere else. Re-exporting
with the same `--slug` replaces that run and keeps the others.

A run's size grows with its number of shots. A real 18-hole trained round of 111 recorded shots
exports to about 2.5 MB of JSON, about 0.6 MB gzipped as Pages serves it (a front-nine round of 54
shots was about 1.2 MB, 0.3 MB gzipped). A mock round is smaller, because it has no neural data.

**Several rounds per brain.** The demo mixes a brain's rounds hole by hole (see *What visitors
see*), so export every round you record for a brain, one slug per round seed
(`trained-eighteen-s07`, `-s08`, …), and never only the good ones. A new readout means
re-recording the trained rounds with the same seeds and replacing the old exports. The demo
should never keep replaying a retired readout.

## Replace the featured run

The featured run is the one the demo opens with, as `featured` in
`apps/web/public/showcase/index.json`.

- Export with `--featured` to make the new run the featured one, or
- edit `"featured"` in `index.json` to the id of another run already in the index.

To remove a run, delete its entry from `index.json` and its file from `runs/`. Then run the tests
and commit. The Pages workflow deploys on the next push to `main`.

## Current showcase

Ten 18-hole rounds per brain, round seeds 7–16 (the seeds of the earlier front-nine showcase),
all recorded from a clean tree at commit `6eceef0` on course `eighteen-v1` (physics
`course-physics-v2`). Each run's `source.run_id` is in its showcase file and in `index.json`.
Strokes are total (out + in):

| ids | Controller | Strokes, seeds 7 to 16 | Summary |
| --- | --- | --- | --- |
| `trained-eighteen-s07` … `-s16` (`-s07` featured) | MaleCNS + trained readout (`hindsight-gated-v2`, readout `20260917T165536Z`, engine `fly-golf-lif-v1`, injection `malecns-sensory-v0.3`) | 115 (54+61), 98 (50+48), 97 (53+44), 103 (50+53), 101 (48+53), 94 (48+46), 93 (49+44), 100 (51+49), 101 (48+53), 94 (42+52) | mean 99.6 (out 49.3, in 50.3), 176 of 180 holes holed, 5 of 10 under 100 |
| `untrained-eighteen-s07` … `-s16` | MaleCNS, fixed a-priori readout (engine `fly-golf-lif-v1`) | 162 (81+81) in every round | no hole finished |
| `mock-eighteen-s07` … `-s16` | MOCK controller: hand-written heuristic, no neurons | 75 (35+40), 73 (36+37), 75 (37+38), 72 (36+36), 75 (36+39), 75 (37+38), 75 (37+38), 74 (37+37), 74 (39+35), 68 (35+33) | mean 73.6 (out 36.5, in 37.1), every hole holed |

Source runs, seeds 7 to 16:

- trained: `20260927T203242Z-f3246f`, `20260927T203530Z-62eb5c`, `20260927T203725Z-e1492e`,
  `20260927T203926Z-15d379`, `20260927T204138Z-79bc76`, `20260927T204351Z-51d8f5`,
  `20260927T204558Z-53936b`, `20260927T204841Z-3ed9b1`, `20260927T205105Z-f3750b`,
  `20260927T205333Z-270f47`
- untrained: `20260927T203242Z-a3f9de`, `20260927T203509Z-fff7a6`, `20260927T203720Z-a8f4b7`,
  `20260927T203928Z-ece591`, `20260927T204138Z-4ab5b8`, `20260927T204344Z-9391cf`,
  `20260927T204604Z-91af3d`, `20260927T204845Z-69a44d`, `20260927T205107Z-db77cd`,
  `20260927T205330Z-5e391a`
- mock: `20260927T203221Z-70984b`, `20260927T203222Z-0c5e0c`, `20260927T203223Z-cdb51f`,
  `20260927T203224Z-dd82c1`, `20260927T203225Z-c3bad6`, `20260927T203227Z-c30c51`,
  `20260927T203228Z-e8f9b4`, `20260927T203229Z-3fd924`, `20260927T203230Z-2a45ca`,
  `20260927T203231Z-4517df`

The seeds were fixed before any round was played, and every round recorded for the showcase is in
it. None was selected from several attempts. Holes 1-9 of every round are stroke for stroke the
earlier front-nine round with the same seed (the trained OUT scores are the old front-nine
scores), so a deep link keeps its shot number: `?run=trained-front-nine-s07&shot=14` is now
`?run=trained-eighteen-s07&shot=14`.

**Does the trained fly break 100?** Sometimes. Five of these ten rounds are under 100; seed 14 is
exactly 100, which does not break 100. On 36 more rounds from fresh seeds (`fly-golf bench`,
seeds 100–111, 200–211, 300–311) it averages 102.6 and breaks 100 in 8 of 36
([TRAINING.md](TRAINING.md#18-hole-results-2026-09-27)): 13 of 46 real 18-hole rounds in all. The
"98.6 over eighteen" quoted before 2026-09-27 was the front-nine average doubled. The back nine,
never practised on, costs it about one to two strokes; that says the readout transfers to unseen
holes, not that the real wiring helps (on the front nine the shuffled-wiring control and the
no-brain readout both beat it, and neither has been run on the back nine). The untrained fly is
nowhere near 100. The mock, which reads the golf state directly and has no neurons, is the
reference, not the fly.

These thirty replaced the 30 front-nine rounds (`*-front-nine-sNN`, commit `04a148d`, recorded as
`43f6d6b`) on 2026-09-27; those slugs no longer exist.

## What visitors see

A splash screen explains that the page shows pre-generated plays and that running the simulation
in real time means cloning the repository (the connectome needs more than 1 GB of disk). With the
18-hole course it also says that the trained fly practised only on the front nine,
so the back nine is ground it has never seen. Visitors pick a brain; each brain with a recorded
solo round is selectable.

**Each hole is drawn at random from the brain's recorded rounds.** For every hole the page picks
one of the brain's complete recorded rounds and plays that round's strokes on that hole,
unchanged. Every hole starts from its tee and the brain resets before every stroke, so a hole
stands on its own (`mixRound` in `apps/web/src/lib/showcase.ts`, tested in `showcase.test.ts`).
A hole is only drawn from a round that played it, so a round recorded on the front nine alone
never supplies a back-nine hole. The mix covers the holes the brain's recordings cover: all 18
once its rounds are 18-hole rounds, the front nine for rounds recorded before the back nine
existed. The scorecard's ROUND row and the note under the controls say which round (seed) and
commit each hole came from, and the total is the sum of the real holes shown. Choosing a brain,
finishing the round or reloading the page draws a new mix; only the rounds the draw needs are
downloaded. A link to one recorded run (`?run=<id>&shot=<n>`) still plays that run exactly as
recorded.

**The 18-hole card and its verdict.** An 18-hole card has two blocks: the Front Nine with its OUT
column and The Neuropil Nine with IN, then TOT. The verdict line under the card names who played:
the trained fly, the untrained fly, or the mock controller, which is never called the fly and
always carries the note that it has no neurons. A complete 18 gives the real total and whether it
broke 100; for the trained fly it adds that the back nine is ground it never practised on. At the
turn it gives the OUT score. A nine-hole card (an older recording) gives its total and the pace
over eighteen, labelled as a pace. A round more than one brain played is never passed off as one
brain's score. The back nine is drawn at dusk (a low golden sun, a gradient sky and its own
palette, `apps/web/src/scene/theme.ts`); the front nine keeps its daylight parkland look.

Shots play one at a time: a shot plays when asked and then waits. The splash reopens from
**About this demo**.

**Watch the brain fire** (the button at the top right of the course, or key **B**) replays each
MaleCNS shot's recorded activity on a map of the fly's brain. The dots are real anatomy: MaleCNS
v1.0 cell-body positions, the brain seen from behind and binned into a halftone
(`apps/web/public/anatomy/malecns-brain-somata.json`, 21 kB, built by
`services/sim/scripts/build_soma_map.py`; CC BY 4.0). The light comes only from the shot's recorded
`neural_summary`: the whole network's spikes per 10 ms brighten every dot together; each sensory and
descending-neuron population glows at its recorded mean rate per neuron, over 0–150 ms and then over
the 150–400 ms readout window; and the 18 named descending neurons each glow at their own recorded
rate. Which individual neurons fired is not recorded, so no single neuron is shown firing on its own.
The antenna, eye-rim and leg neurons have their cell bodies outside the imaged brain, so they are
listed as readings, not placed on the map. The 400 ms of neural time replay about 6× slower while
the fly picks its club, addresses the ball and lines up (in the simulation all of it happened
before the fly moved). The result holds through the swing, and the map goes dark while the ball
moves. Mock shots have no neural activity, and the view says so. With reduced motion, the whole
window shows at once. The same view works in the live app.
