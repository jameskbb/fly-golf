# Fly Golf developer entry points. Every target wraps a pnpm/uv command, so
# Windows users without make can run the equivalent `pnpm run <script>` (see README).

UV   ?= uv
PNPM ?= pnpm
SIM  := $(UV) --directory services/sim

.PHONY: help setup dev test test-sim test-web test-integration lint format build data data-status verify-source lif-reference putt smoke clean

help:
	@echo "make setup            install backend (uv) + frontend (pnpm) dependencies"
	@echo "make dev              run backend (http://127.0.0.1:8000) + frontend (http://localhost:5173)"
	@echo "make test             run all unit tests (no connectome needed)"
	@echo "make test-integration run tests that need the compiled MaleCNS graph"
	@echo "make lint             ruff + eslint + tsc"
	@echo "make build            production build of the web app"
	@echo "make data             download (~1.1 GB), verify and compile MaleCNS v1.0"
	@echo "make data-status      show which data artifacts exist"
	@echo "make verify-source    check the local MaleCNS files against the lock, and the lock against the official release"
	@echo "make lif-reference    regenerate the Brian2 reference results for the LIF parity suite (needs the reference group)"
	@echo "make putt             one headless MOCK putt from the command line"

setup:
	$(PNPM) install
	$(SIM) sync

dev:
	$(PNPM) run dev

test: test-sim test-web

test-sim:
	$(SIM) run pytest

test-web:
	$(PNPM) -r --if-present run test

test-integration:
	$(SIM) run pytest -m integration

lint:
	$(SIM) run ruff check .
	$(SIM) run ruff format --check .
	$(PNPM) -r --if-present run lint
	$(PNPM) -r --if-present run typecheck

format:
	$(SIM) run ruff format .
	$(SIM) run ruff check --fix .
	$(PNPM) -r --if-present run format

build:
	$(PNPM) --filter @fly-golf/web build

data:
	$(SIM) run fly-golf-data prepare

data-status:
	$(SIM) run fly-golf-data status

verify-source:
	$(SIM) run fly-golf-data verify-source --remote

lif-reference:
	$(SIM) run --group reference python scripts/generate_lif_reference.py

putt:
	$(SIM) run fly-golf putt --controller mock --seed 7

smoke:
	$(SIM) run python -m fly_golf.smoke

clean:
	rm -rf apps/web/dist runs .pytest_cache services/sim/.pytest_cache
