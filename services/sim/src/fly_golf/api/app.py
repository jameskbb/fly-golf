"""Fly Golf backend API.

REST:
    GET  /health                 liveness + versions
    GET  /api/status             controllers, MaleCNS data status, session state
    GET  /api/course             the front nine (every hole's geometry) + the club bag
    POST /api/session            choose controller + mode (starts a new recorded run)
    POST /api/controller         swap the controller mid-round (same run, hole and ball)
    POST /api/reset              practice: new hole (optional seed); course: new round / chosen hole
    POST /api/next               course: go to the next hole (or a new round after the ninth)
    POST /api/shot               play one stroke with the active controller (/api/putt is an alias)
    GET  /api/runs               list recorded runs
    GET  /api/runs/{run_id}      one run with all shot records
    GET  /api/runs/{run_id}/shots/{shot_id}/replay   deterministic physics replay
WebSocket:
    WS   /ws/simulation          hello handshake, then pushed state / shot events
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .. import PROTOCOL_VERSION, __version__
from ..brain.registry import ControllerRegistry
from ..config import Settings, load_settings
from ..experiments.runner import (
    COURSE_EXPERIMENT_ID,
    EXPERIMENT_ID,
    PuttingSession,
    RoundSession,
    RunRecorder,
    list_runs,
    load_run,
    replay_physics,
)
from ..golf.clubs import BAG, nominal_distances
from ..golf.course import COURSE_NAME, COURSE_PAR, COURSE_VERSION, FRONT_NINE
from ..provenance import git_info
from .schemas import ClientHello, ControllerRequest, Envelope, ResetRequest, SessionRequest, envelope

DEFAULT_MODE = "course"


class SimulationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.registry = ControllerRegistry(settings)
        self.session: PuttingSession | RoundSession | None = None
        self.controller_id = "mock"
        self.mode = DEFAULT_MODE
        self.busy = False
        self.lock = asyncio.Lock()
        self.clients: set[WebSocket] = set()
        self.seq = 0
        self._seed_rng = random.SystemRandom()
        self.loop: asyncio.AbstractEventLoop | None = None

    def next_seed(self) -> int:
        return self._seed_rng.randrange(0, 1_000_000)

    async def broadcast(self, type_: str, data: dict) -> None:
        self.seq += 1
        msg = envelope(type_, data, self.seq)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def status(self) -> dict:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "server_version": __version__,
            "git": git_info(),
            "controllers": self.registry.available(),
            "active_controller": self.controller_id,
            "mode": self.mode,
            "malecns": self.registry.malecns_status(),
            "busy": self.busy,
            "session": self.session.state() if self.session else None,
        }

    async def _load(self, controller_id: str):
        """Build (or fetch the cached) controller; refuse, never fake, an unavailable one."""
        await self.broadcast("controller_status", {"controller": controller_id, "status": "loading"})
        try:
            return await asyncio.to_thread(self.registry.get, controller_id)
        except FileNotFoundError as exc:
            await self.broadcast("controller_status", {"controller": controller_id, "status": "unavailable"})
            raise HTTPException(
                status_code=409, detail={"code": "controller_unavailable", "message": str(exc)}
            ) from exc
        except Exception as exc:
            await self.broadcast(
                "controller_status", {"controller": controller_id, "status": "error", "message": str(exc)}
            )
            raise HTTPException(status_code=500, detail={"code": "internal", "message": str(exc)}) from exc

    async def switch_controller(self, controller_id: str) -> dict:
        """Swap the brain on the live session: round, hole, ball and scorecard stay as they are."""
        if self.session is None or self.session.env is None:
            return await self.start_session(controller_id, None, self.mode)
        controller = await self._load(controller_id)
        self.session.set_controller(controller)
        self.controller_id = controller_id
        await self.broadcast(
            "controller_status",
            {"controller": controller_id, "status": "ready", "info": controller.info.to_dict()},
        )
        state = self.session.state()
        await self.broadcast("state", state)
        return state

    async def start_session(self, controller_id: str, seed: int | None, mode: str = DEFAULT_MODE) -> dict:
        controller = await self._load(controller_id)
        recorder = RunRecorder(
            self.settings.runs_dir,
            metadata={
                "controller": controller.info.to_dict(),
                "mode": mode,
                "experiment_id": COURSE_EXPERIMENT_ID if mode == "course" else EXPERIMENT_ID,
            },
        )
        seed = self.next_seed() if seed is None else seed
        if mode == "course":
            self.session = RoundSession(controller, recorder=recorder, detailed_traces=self.settings.detailed_traces)
            state = self.session.new_round(seed)
        else:
            self.session = PuttingSession(controller, recorder=recorder, detailed_traces=self.settings.detailed_traces)
            state = self.session.new_hole(seed)
        self.controller_id = controller_id
        self.mode = mode
        await self.broadcast(
            "controller_status",
            {"controller": controller_id, "status": "ready", "info": controller.info.to_dict()},
        )
        await self.broadcast("state", state)
        return state


def course_payload() -> dict:
    return {
        "name": COURSE_NAME,
        "version": COURSE_VERSION,
        "par": COURSE_PAR,
        "holes": [h.to_dict() for h in FRONT_NINE],
        "clubs": [c.to_dict() | {"nominal": nominal_distances().get(c.id)} for c in BAG],
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = SimulationService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.loop = asyncio.get_running_loop()
        await service.start_session("mock", None, DEFAULT_MODE)
        yield

    app = FastAPI(title="Fly Golf simulation", version=__version__, lifespan=lifespan)
    app.state.service = service

    def bad(message: str, code: int = 409) -> HTTPException:
        return HTTPException(code, detail={"code": "bad_request", "message": message})

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "service": "fly-golf-sim",
            "version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "git_commit": git_info()["commit"],
        }

    @app.get("/api/status")
    async def status() -> dict:
        return service.status()

    @app.get("/api/course")
    async def course() -> dict:
        return course_payload()

    @app.post("/api/session")
    async def session(req: SessionRequest) -> dict:
        async with service.lock:
            return await service.start_session(req.controller, req.seed, req.mode or service.mode)

    @app.post("/api/controller")
    async def switch_controller(req: ControllerRequest) -> dict:
        if service.lock.locked():
            raise bad("busy (a shot, a reset or a brain loading); switch brains when it finishes")
        async with service.lock:
            return await service.switch_controller(req.controller)

    @app.post("/api/reset")
    async def reset(req: ResetRequest | None = None) -> dict:
        req = req or ResetRequest()
        async with service.lock:
            s = service.session
            if s is None:
                raise bad("no session")
            if isinstance(s, RoundSession):
                if req.hole is not None and req.seed is None:
                    state = s.start_hole(req.hole)
                else:
                    seed = service.next_seed() if req.seed is None else req.seed
                    state = s.new_round(seed, start_hole=req.hole or 1)
            else:
                state = s.new_hole(service.next_seed() if req.seed is None else req.seed)
            await service.broadcast("state", state)
            return state

    @app.post("/api/next")
    async def next_hole() -> dict:
        async with service.lock:
            s = service.session
            if not isinstance(s, RoundSession):
                raise bad("next hole is only for course mode; use /api/reset on the practice green")
            try:
                state = s.next_hole()
            except RuntimeError as exc:
                raise bad(str(exc)) from exc
            await service.broadcast("state", state)
            return state

    async def play() -> dict:
        if service.lock.locked():
            raise bad("busy (a shot, a reset or a brain loading); try again when it finishes")
        async with service.lock:
            s = service.session
            if s is None or s.env is None:
                raise bad("no hole in play")
            if s.env.done:
                raise bad("hole finished; start the next hole")
            loop = asyncio.get_running_loop()

            def on_phase(phase: str, data: dict) -> None:
                asyncio.run_coroutine_threadsafe(service.broadcast("shot_phase", {"phase": phase, **data}), loop)

            service.busy = True
            try:
                record = await asyncio.to_thread(s.play_shot, on_phase)
            finally:
                service.busy = False
            await service.broadcast("shot_result", record)
            await service.broadcast("state", s.state())
            return record

    @app.post("/api/shot")
    async def shot() -> dict:
        return await play()

    @app.post("/api/putt")
    async def putt() -> dict:
        return await play()

    # File I/O runs in a worker thread so large run directories never block the event loop.
    @app.get("/api/runs")
    async def runs() -> dict:
        return {"runs": await asyncio.to_thread(list_runs, settings.runs_dir)}

    @app.get("/api/runs/{run_id}")
    async def run(run_id: str) -> dict:
        data = await asyncio.to_thread(load_run, settings.runs_dir, run_id)
        if data is None:
            raise HTTPException(404, detail={"code": "bad_request", "message": "run not found"})
        return data

    @app.get("/api/runs/{run_id}/shots/{shot_id}/replay")
    async def replay(run_id: str, shot_id: str) -> dict:
        data = await asyncio.to_thread(load_run, settings.runs_dir, run_id)
        if data is None:
            raise HTTPException(404, detail={"code": "bad_request", "message": "run not found"})
        for shot in data["shots"]:
            if shot["shot_id"] == shot_id:
                return {"record": shot, "replay": replay_physics(shot)}
        raise HTTPException(404, detail={"code": "bad_request", "message": "shot not found"})

    @app.websocket("/ws/simulation")
    async def ws_simulation(ws: WebSocket) -> None:
        async def reject(code: str, message: str, close_code: int) -> None:
            with contextlib.suppress(Exception):  # the client may already be gone
                data = {"code": code, "message": message}
                if code == "protocol_mismatch":
                    data["server_protocol_version"] = PROTOCOL_VERSION
                await ws.send_json(envelope("error", data))
                await ws.close(code=close_code)

        await ws.accept()
        try:
            await ws.send_json(
                envelope(
                    "hello",
                    {"server": "fly-golf-sim", "server_version": __version__, "protocol_version": PROTOCOL_VERSION},
                )
            )
            first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        except WebSocketDisconnect:
            return  # client left before the handshake; nothing to report
        except Exception:
            await reject("bad_request", "expected a JSON client hello within 10 s", 4000)
            return
        try:
            env = Envelope.model_validate(first)
        except ValidationError:
            await reject("bad_request", "first message is not a valid protocol envelope", 4000)
            return
        if env.type != "hello":
            await reject("bad_request", f"first message must be 'hello', got {env.type!r}", 4000)
            return
        try:
            hello = ClientHello.model_validate(env.data)
        except ValidationError:
            await reject("bad_request", "client hello is missing 'client' or 'protocol_version'", 4000)
            return
        if hello.protocol_version != PROTOCOL_VERSION or env.protocol_version != PROTOCOL_VERSION:
            await reject(
                "protocol_mismatch",
                f"client protocol {hello.protocol_version} != server protocol {PROTOCOL_VERSION}; "
                "rebuild the frontend and backend from the same commit",
                4001,
            )
            return
        service.clients.add(ws)
        await ws.send_json(envelope("state", service.session.state() if service.session else {}))
        try:
            while True:
                # Commands go through REST; ignore anything else but keep the socket alive.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            service.clients.discard(ws)
            with contextlib.suppress(Exception):
                await ws.close()

    return app


app = create_app()
