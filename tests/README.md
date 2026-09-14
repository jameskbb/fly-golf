# Tests

Tests live next to the code they check:

| Suite | Location | Run |
| --- | --- | --- |
| Backend unit tests: physics, controllers, runner, engine, adapter, API | `services/sim/tests/` | `make test-sim` |
| Real-connectome integration tests (need `make data`, auto-skip otherwise) | `services/sim/tests/test_malecns_adapter.py` (`-m integration`) | `make test-integration` |
| Cross-stack protocol contract | `packages/protocol/fixtures/*.json`, validated by `packages/protocol/test/` (zod) **and** `services/sim/tests/test_api.py` (pydantic) | `make test` |
| Frontend logic: swing timeline, coordinates | `apps/web/src/**/*.test.ts` | `make test-web` |
| Showcase: exporter (`services/sim/tests/test_showcase_export.py`); the committed showcase files validated by pydantic **and** zod, with each round's scorecard rebuilt from its shots (`apps/web/src/lib/showcase.test.ts`) | both | `make test` |
| Startup smoke test: real uvicorn + `/health` + `/api/status` | `services/sim/src/fly_golf/smoke.py` | `make smoke` |

The shared JSON fixtures in `packages/protocol/fixtures/` are this directory's cross-stack
contract. The `shot_result.json` fixture was generated from a real MOCK shot.
