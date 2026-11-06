# Fly Golf: agent rules

`CLAUDE.md` and `AGENTS.md` are the same document under two names so Claude
Code and Codex follow identical rules. Change both together and keep them
byte-identical.

## Purpose

Fly Golf connects a simulated *Drosophila* nervous system to a 3D golf
environment and asks: can a simulated fruit fly nervous system learn to play
golf? Activity propagating through the reconstructed MaleCNS v1.0 connectome
perceives a golf scene and produces motor output for a shot; an animated 3D fly
executes it in the browser while a deterministic Python backend runs the golf
physics. It serves two audiences at once: a broadcast-style spectacle for
non-technical viewers and a scientifically transparent instrument for technical
ones.

Core value: a shot whose control signals genuinely originate from simulated
neural dynamics over the real connectome, visible in 3D, recorded as a
reproducible experiment, and honestly labelled. A failed real-connectome putt is
worth more than a faked successful one.

This repository is public. Everything committed here is published.

## Layout and stack

- `services/sim/`: Python 3.12+ backend (FastAPI, WebSockets, NumPy/SciPy,
  pandas/pyarrow, CSR sparse, optional Numba), managed with `uv`, tested with
  pytest. CLIs: `fly-golf` and `fly-golf-data`.
- `apps/web/`: TypeScript, React, Vite, Three.js / React Three Fiber / Drei,
  Zustand. pnpm workspace (`packages/` holds shared packages such as the
  protocol).
- `apps/web/public/showcase/`: the recorded rounds Showcase Mode replays,
  exported with `fly-golf export-showcase` and committed.
- `data/`: connectome tooling; raw, normalized and compiled data are never
  committed. `runs/`: experiment output, not committed.
- `docs/`: course, mapping, engine, training, provenance and build-log
  documentation. `social/`: sources for the published shorts.

## Install, run, test

```sh
make setup              # uv sync + pnpm install
make dev                # backend http://127.0.0.1:8000 + app http://localhost:5173
make test               # all unit tests, no connectome needed
make lint               # ruff + eslint + prettier + tsc
make build              # production build of the web app
make showcase           # Showcase Mode (recorded runs, no backend)
make data               # optional: download (~1.1 GB), verify and compile MaleCNS v1.0
make test-integration   # tests that need the compiled graph
```

Without `make`, use the matching `pnpm run <script>` from `package.json`. CI
(`.github/workflows/ci.yml`) runs ruff, pytest, the backend smoke test, web lint,
typecheck, tests and both web builds; it never downloads the connectome.

## Branch model and landing

- Single branch `main`; no separate prod branch. Commit on `main` and push.
- Pushing `main` also deploys Showcase Mode to GitHub Pages
  (`.github/workflows/pages.yml`).
- Run `make test` and `make lint` before pushing a code change.

## Constraints

- **Honesty**: the active controller mode is always visible; no mock result is
  ever presented as connectome-driven; every sensory and motor mapping is
  documented in `docs/`.
- **Data**: never commit raw or compiled connectome files; `make data` must
  acquire, checksum-validate and compile them. CI uses mock and small synthetic
  graph fixtures only.
- **Determinism**: physics and the deterministic parts of a run reproduce given
  commit, config, seed and initial state; the backend owns time. Changing a
  course, physics or mapping bumps its version so old records still replay.
- **Memory**: the full graph is large; run one full-graph process at a time.
- **Licensing**: keep the DOOMFLY MIT and Shiu MIT notices for adapted code and
  the CC BY 4.0 attribution for MaleCNS (`THIRD_PARTY_NOTICES.md`).

## Never do

- Never commit credentials or neuPrint tokens; only `.env.example` is tracked.
- Never commit `.planning/`, `.claude/settings.local.json` or `.claude/worktrees/`.
- Never commit machine-local paths (home directories, drive letters) or private
  network addresses; readouts and reports use repository-relative paths.
- Never write an em dash in any file, comment, UI text or commit message.
  Reword with a colon, semicolon, comma, parentheses or a new sentence.
- Never add AI attribution trailers (`Co-Authored-By`, "Generated with") to
  commit messages in this public repository.
- Never force-push or rewrite published history.
- This repo has a UI: a change to the interface updates the README's
  screenshots and media (`docs/screenshots/`, `docs/media/`) in the same change.
