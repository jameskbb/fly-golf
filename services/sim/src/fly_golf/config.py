"""Runtime configuration from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def repo_root() -> Path:
    """Locate the repository root (the directory holding data/malecns_v1.lock.json)."""
    env = os.environ.get("FLY_GOLF_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "malecns_v1.lock.json").exists():
            return parent
    return Path.cwd()


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_dir: Path
    runs_dir: Path
    api_host: str
    api_port: int
    detailed_traces: bool

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" / "malecns_v1"

    @property
    def compiled_dir(self) -> Path:
        return self.data_dir / "compiled" / "malecns_v1"

    @property
    def lock_path(self) -> Path:
        return self.repo_root / "data" / "malecns_v1.lock.json"


def load_settings() -> Settings:
    root = repo_root()
    data_dir = Path(os.environ.get("FLY_GOLF_DATA_DIR", root / "data")).resolve()
    runs_dir = Path(os.environ.get("FLY_GOLF_RUNS_DIR", root / "runs")).resolve()
    return Settings(
        repo_root=root,
        data_dir=data_dir,
        runs_dir=runs_dir,
        api_host=os.environ.get("FLY_GOLF_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("FLY_GOLF_API_PORT", "8000")),
        detailed_traces=os.environ.get("FLY_GOLF_DETAILED_TRACES", "0").lower() in {"1", "true", "yes"},
    )
