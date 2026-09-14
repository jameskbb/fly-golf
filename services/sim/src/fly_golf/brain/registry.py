"""Controller registry: which controllers exist, whether they are usable, and
lazy construction (the MaleCNS graph is loaded once and cached)."""

from __future__ import annotations

import threading
import time

from ..config import Settings
from ..data.prepare import compiled_status
from .interfaces import BrainController
from .mock import MockBrainController

FIX_DATA_COMMAND = "make data"
READOUT_RELPATH = "experiments/readouts/malecns-readout-v1.json"
READOUT_ARCHIVE_RELPATH = "experiments/readouts/archive"  # retired readouts, by training id


class ControllerRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._malecns = None
        self._trained = None
        self._graph = None
        self._malecns_state = "unloaded"  # unloaded | loading | loaded | error
        self._malecns_error: str | None = None
        self._malecns_load_s: float | None = None
        self._replay: dict[tuple, BrainController] = {}

    @property
    def readout_path(self):
        return self.settings.repo_root / READOUT_RELPATH

    def malecns_status(self) -> dict:
        c = compiled_status(self.settings)
        if self._malecns_state in ("loading", "loaded", "error"):
            status = self._malecns_state
        else:
            status = "ready" if c["ready"] else "unavailable"
        m = c.get("manifest") or {}
        return {
            "status": status,
            "compiled": c["ready"],
            "missing": c["missing"],
            "neurons": m.get("neurons"),
            "edges": m.get("edges"),
            "release": m.get("release"),
            "error": self._malecns_error,
            "load_seconds": self._malecns_load_s,
            "fix_command": None if c["ready"] else FIX_DATA_COMMAND,
        }

    def available(self) -> list[dict]:
        mock = MockBrainController().info.to_dict()
        ms = self.malecns_status()
        has_readout = self.readout_path.exists()
        malecns = {
            "kind": "malecns",
            "is_mock": False,
            "status": ms["status"],
            "neuron_count": ms["neurons"],
            "edge_count": ms["edges"],
            "fix_command": ms["fix_command"],
        }
        return [
            {**mock, "available": True, "status": "ready"},
            {**malecns, "id": "malecns", "label": "MaleCNS LIVE", "available": ms["compiled"]},
            {
                **malecns,
                "id": "malecns-trained",
                "label": "MaleCNS + TRAINED READOUT",
                "available": ms["compiled"] and has_readout,
                "fix_command": ms["fix_command"] or (None if has_readout else "fly-golf train"),
            },
        ]

    def get(self, controller_id: str) -> BrainController:
        if controller_id == "mock":
            return MockBrainController()
        if controller_id == "malecns":
            return self._get_malecns()
        if controller_id == "malecns-trained":
            return self._get_trained()
        raise KeyError(f"unknown controller {controller_id!r}")

    def _load_graph(self):
        """Load the compiled graph once (caller holds the lock); shared by both MaleCNS controllers."""
        if self._graph is not None:
            return self._graph
        c = compiled_status(self.settings)
        if not c["ready"]:
            raise FileNotFoundError(
                f"MaleCNS compiled graph not found in {c['dir']} (missing {c['missing']}). Run `{FIX_DATA_COMMAND}`."
            )
        from .malecns.graph import load_compiled

        self._graph = load_compiled(self.settings.compiled_dir)
        return self._graph

    def _build(self, factory):
        self._malecns_state = "loading"
        t0 = time.perf_counter()
        try:
            ctrl = factory(self._load_graph())
            # Warm the Numba JIT so the first shot is not dominated by compilation.
            ctrl.engine.run(1.0)
            ctrl.engine.reset()
        except FileNotFoundError:
            self._malecns_state = "unloaded"
            raise
        except Exception as exc:  # surface to the UI, never silently fall back to the mock
            self._malecns_state = "error"
            self._malecns_error = f"{type(exc).__name__}: {exc}"
            raise
        self._malecns_state = "loaded"
        self._malecns_load_s = round(time.perf_counter() - t0, 2)
        return ctrl

    def _get_malecns(self) -> BrainController:
        with self._lock:
            if self._malecns is None:
                from .malecns.controller import MaleCNSController

                self._malecns = self._build(MaleCNSController)
            return self._malecns

    def find_readout(self, training_id: str | None):
        """The installed readout if it has this training id, else the archived one (for replay)."""
        from .trained import load_readout

        if self.readout_path.exists():
            installed = load_readout(self.readout_path)
            if training_id is None or installed.meta.get("training_id") == training_id:
                return installed, READOUT_RELPATH
        archived = self.settings.repo_root / READOUT_ARCHIVE_RELPATH / f"{training_id}.json"
        if training_id and archived.exists():
            return load_readout(archived), f"{READOUT_ARCHIVE_RELPATH}/{training_id}.json"
        raise FileNotFoundError(f"readout {training_id!r} is neither installed nor in {READOUT_ARCHIVE_RELPATH}/")

    def replay_controller(self, record: dict) -> BrainController:
        """A controller that reproduces a recorded shot: the same controller kind, the neural engine
        it recorded (`controller.model`) and, for trained shots, the same readout."""
        info = record["controller"]
        cid = info["id"]
        if cid == "mock":
            return MockBrainController()
        engine = info.get("model")
        readout_id = ((info.get("config") or {}).get("readout") or {}).get("id") if cid == "malecns-trained" else None
        key = (cid, engine, readout_id)
        with self._lock:
            if key not in self._replay:
                graph = self._load_graph()
                if cid == "malecns":
                    from .malecns.controller import MaleCNSController

                    self._replay[key] = MaleCNSController(graph, engine=engine)
                elif cid == "malecns-trained":
                    from .trained import TrainedReadoutController

                    readout, path = self.find_readout(readout_id)
                    self._replay[key] = TrainedReadoutController(graph, readout, path, engine=engine)
                else:
                    raise KeyError(f"unknown controller {cid!r}")
            return self._replay[key]

    def _get_trained(self) -> BrainController:
        with self._lock:
            if self._trained is None:
                if not self.readout_path.exists():
                    raise FileNotFoundError(f"no trained readout at {self.readout_path}. Run `fly-golf train`.")
                from .trained import TrainedReadoutController, load_readout

                readout = load_readout(self.readout_path)
                self._trained = self._build(lambda g: TrainedReadoutController(g, readout, READOUT_RELPATH))
            return self._trained
