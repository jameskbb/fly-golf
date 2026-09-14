"""Typed wire protocol (mirrors packages/protocol/src/*.ts).

Every WebSocket message is an envelope {type, protocol_version, seq, data}.
Contract tests validate the shared fixtures in packages/protocol/fixtures/
against these models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import PROTOCOL_VERSION

MessageType = Literal[
    "hello",  # server -> client on connect; client -> server to declare its version
    "error",
    "state",  # full session state snapshot
    "controller_status",
    "shot_phase",  # sensing | thinking | swinging | result
    "shot_result",  # full shot record
]


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: MessageType
    protocol_version: int
    seq: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class ServerHello(BaseModel):
    model_config = ConfigDict(extra="allow")
    server: Literal["fly-golf-sim"]
    server_version: str
    protocol_version: int


class ClientHello(BaseModel):
    model_config = ConfigDict(extra="allow")
    client: str
    protocol_version: int


class ErrorData(BaseModel):
    code: Literal["protocol_mismatch", "bad_request", "controller_unavailable", "internal"]
    message: str
    server_protocol_version: int | None = None


class ControllerInfoModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    kind: Literal["mock", "malecns"]
    label: str
    is_mock: bool


class OutcomeModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    outcome: Literal["holed", "stopped", "off_green", "timeout", "no_contact", "water", "out_of_bounds"]
    holed: bool
    start_distance_m: float
    final_distance_m: float
    strokes: int
    reward: float


class TrajectoryModel(BaseModel):
    sample_hz: int
    points: list[list[float]]
    events: list[dict[str, Any]] = Field(default_factory=list)


class ShotRecordModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    record_type: Literal["shot"]
    schema_version: int
    shot_id: str
    run_id: str | None
    seed: int
    controller: ControllerInfoModel
    sensory: dict[str, Any]
    motor: dict[str, Any]
    stroke: dict[str, Any]
    trajectory: TrajectoryModel
    outcome: OutcomeModel
    neural_summary: dict[str, Any] | None


ControllerId = Literal["mock", "malecns", "malecns-trained"]
Mode = Literal["practice", "course"]


class SessionRequest(BaseModel):
    controller: ControllerId = "mock"
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    mode: Mode | None = None  # None: keep the server's current mode


class ControllerRequest(BaseModel):
    controller: ControllerId


class ResetRequest(BaseModel):
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    hole: int | None = Field(default=None, ge=1, le=9)  # course mode: play this hole


def envelope(type_: str, data: dict, seq: int = 0) -> dict:
    return {"type": type_, "protocol_version": PROTOCOL_VERSION, "seq": seq, "data": data}
