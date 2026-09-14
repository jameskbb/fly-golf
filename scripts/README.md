# Scripts

Developer entry points are exposed as `make` targets, which wrap the root `package.json` scripts,
so they work on Windows without make:

| Task | make | pnpm |
| --- | --- | --- |
| Install everything | `make setup` | `pnpm run setup` |
| Backend + frontend dev servers | `make dev` | `pnpm run dev` |
| All tests | `make test` | `pnpm run test` |
| Lint and typecheck | `make lint` | `pnpm run lint` |
| Download, verify and compile MaleCNS | `make data` | `pnpm run data` |
| Data status | `make data-status` | `pnpm run data:status` |
| One headless mock putt | `make putt` | `pnpm run putt` |
| Server smoke test | `make smoke` | — |
| Web demo (showcase mode, no backend) | `make showcase` | `pnpm showcase` |
| GitHub Pages build and preview | `make build-showcase` / `make preview-showcase` | `pnpm build:showcase` / `pnpm preview` |
| Export a recorded run to the web demo | — | `pnpm export-showcase <run_id> --slug … --title …` |

The Python CLIs are `fly-golf` (`serve`, `putt`, `round`, `train`, `refit`, `bench`, `runs`,
`replay`, `export-showcase`) and `fly-golf-data` (`status`, `prepare`, `verify-source`, `lock`).
Run them with `uv --directory services/sim run <cli> --help`.
