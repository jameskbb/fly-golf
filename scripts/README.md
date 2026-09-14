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

The Python CLIs are `fly-golf` (`serve`, `putt`, `runs`, `replay`) and `fly-golf-data`
(`status`, `prepare`). Run them with `uv --directory services/sim run <cli> --help`.
