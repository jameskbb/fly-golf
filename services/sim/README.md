# fly-golf-sim

Python backend for Fly Golf. It provides:

- `fly_golf.golf` — the deterministic, backend-authoritative putting green: physics, scenarios and environment
- `fly_golf.brain` — the sensory encoder, the `BrainController` protocol, the MOCK controller, and the motor decoder and motor targets
- `fly_golf.brain.malecns` — the MaleCNS v1.0 adapter: graph loading, the `fly-golf-lif-v1` LIF engine (docs/LIF_ENGINE.md), the sign proxy and population mappings; `legacy_engine.py` keeps the previous engine for replaying old records
- `fly_golf.experiments` — the episode runner, JSONL run recorder, deterministic replay, the front-nine bench, and the showcase exporter (`fly-golf export-showcase`, docs/GITHUB_PAGES.md)
- `fly_golf.data` — `fly-golf-data prepare | status | verify-source | lock`: acquires the official MaleCNS files, verifies them against the lock and compiles the graph (`compiler.py`)
- `fly_golf.api` — the FastAPI app with REST endpoints and `WS /ws/simulation`

Run everything through the repository root: `make setup`, `make dev`, `make test`.
Direct use:

```sh
uv sync
uv run pytest
uv run fly-golf putt --controller mock --seed 7
uv run fly-golf serve
```
