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

## Replace the featured run

The featured run is the one the demo opens with, as `featured` in
`apps/web/public/showcase/index.json`.

- Export with `--featured` to make the new run the featured one, or
- edit `"featured"` in `index.json` to the id of another run already in the index.

To remove a run, delete its entry from `index.json` and its file from `runs/`. Then run the tests
and commit. The Pages workflow deploys on the next push to `main`.

## Current showcase

| id | Controller | Source run | Recorded at | Round |
| --- | --- | --- | --- | --- |
| `trained-front-nine` (featured) | MaleCNS + trained readout (`hindsight-gated-v2`, readout `20260913T220118Z`, engine `fly-golf-lif-v1`) | `20260914T115447Z-e62f18` | commit `fd29296`, clean tree | seed 7: 58 strokes (+22), 7 of 9 holes holed |
| `untrained-front-nine` | MaleCNS, fixed a-priori readout (engine `fly-golf-lif-v1`) | `20260914T115447Z-81909c` | commit `fd29296`, clean tree | seed 7: 81 strokes (+45), no hole finished |

Both rounds were played with the project's default seed (7), chosen before either round was
played, and they are the only rounds recorded for the showcase. Neither was selected from several
attempts. On an 18-hole pace the trained fly shoots 116 and the untrained fly 162: neither breaks
100 yet.
