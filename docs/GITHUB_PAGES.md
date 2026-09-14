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
uv --directory services/sim run fly-golf round --controller malecns-trained --seed 7
#    -> recorded run: runs/<run_id>

# 2. Export into apps/web/public/showcase/ (validates every shot; never modifies the run).
uv --directory services/sim run fly-golf export-showcase <run_id> \
  --slug trained-front-nine \
  --title "Trained MaleCNS - Front Nine" \
  --description "One or two honest sentences about what this run is."

# 3. Check, then commit the JSON.
pnpm -r test && uv --directory services/sim run pytest tests/test_showcase_export.py
```

The exporter prints the file size and any notes, for example on shots from abandoned attempts
that were left out, a dirty working tree, or removed local paths. It refuses to export:

- a run that fails `ShotRecord` validation, or practice-green runs (the showcase shows the course);
- a round recorded on a different course version from the current code;
- a MaleCNS shot without recorded neural activity;
- a run containing MOCK shots under a title that claims MaleCNS or the connectome.

Use `--round <seed>` when a run holds several rounds. `--out` writes somewhere else. Re-exporting
with the same `--slug` replaces that run and keeps the others.

A full front-nine run is about 1.2 MB of JSON, about 0.3 MB gzipped, as Pages serves it.

**Several rounds per brain.** The demo mixes a brain's rounds hole by hole (see *What visitors
see*), so export every round you record for a brain, one slug per round seed
(`trained-front-nine-s07`, `-s08`, …), and never only the good ones. A new readout means
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

Ten rounds per brain, round seeds 7–16, all recorded from a clean tree at commit `dd1e393`
(each run's `source.run_id` is in its showcase file):

| ids | Controller | Strokes, seeds 7 to 16 | Summary |
| --- | --- | --- | --- |
| `trained-front-nine-s07` … `-s16` (`-s07` featured) | MaleCNS + trained readout (`hindsight-gated-v2`, readout `20260914T191715Z-refit`, engine `fly-golf-lif-v1`) | 60, 70, 71, 72, 64, 70, 57, 75, 71, 75 | mean 68.5, 56 of 90 holes holed |
| `untrained-front-nine-s07` … `-s16` | MaleCNS, fixed a-priori readout (engine `fly-golf-lif-v1`) | 81 in every round | no hole finished |
| `mock-front-nine-s07` … `-s16` | MOCK controller: hand-written heuristic, no neurons | 35, 36, 37, 36, 36, 37, 37, 37, 39, 35 | mean 36.5, every hole holed |

The seeds were fixed before any round was played, and every round recorded for the showcase is in
it. None was selected from several attempts. 23 of the 30 were recorded twice: the first
recording of them was stamped `dirty` because an untracked directory of agent worktrees sat in the
checkout. They were re-recorded from a clean worktree, and every re-recording is identical, stroke
for stroke. On an 18-hole pace the trained fly averages 137 and the untrained fly 162: neither
breaks 100 yet. The mock, which reads the golf state directly and has no neurons, is the
reference.

## What visitors see

A splash screen explains that the page shows pre-generated plays and that running the simulation
in real time means cloning the repository (the connectome needs more than 1 GB of disk). Visitors
pick a brain; each brain with a recorded solo round is selectable.

**Each hole is drawn at random from the brain's recorded rounds.** For every hole the page picks
one of the brain's complete recorded rounds and plays that round's strokes on that hole,
unchanged. Every hole starts from its tee and the brain resets before every stroke, so a hole
stands on its own (`mixRound` in `apps/web/src/lib/showcase.ts`, tested in `showcase.test.ts`).
The scorecard's ROUND row and the note under the controls say which round (seed) and commit each
hole came from, and the total is the sum of the nine real holes shown. Choosing a brain, finishing
the nine or reloading the page draws a new mix; only the rounds the draw needs are downloaded. A
link to one recorded run (`?run=<id>&shot=<n>`) still plays that run exactly as recorded.

Shots play one at a time: a shot plays when asked and then waits. The splash reopens from
**About this demo**.
