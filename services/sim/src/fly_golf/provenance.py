"""Provenance helpers: git state and the version stamp written into every record."""

from __future__ import annotations

import subprocess

from . import PROTOCOL_VERSION, __version__
from .config import repo_root


def git_info() -> dict:
    """Current commit and whether the working tree differs from it.

    Evaluated on every call (never cached), so a long-running server records the
    state at the time of each shot. `dirty` counts modified AND untracked
    (non-ignored) files, so uncommitted new code cannot masquerade as the commit.
    """
    root = repo_root()
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        describe = subprocess.run(
            ["git", "-C", str(root), "describe", "--always", "--dirty", "--broken"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unknown", "dirty": None, "describe": None}
    return {"commit": commit, "dirty": bool(status.strip()), "describe": describe or None}


def versions() -> dict:
    from .brain.motor import MOTOR_MAPPING_VERSION_V2
    from .brain.sensory import SENSORY_MAPPING_VERSION_V2
    from .golf.clubs import CLUBS_VERSION
    from .golf.course import COURSE_VERSION
    from .golf.course_env import COURSE_REWARD_VERSION
    from .golf.env import REWARD_VERSION
    from .golf.flight import COURSE_PHYSICS_VERSION
    from .golf.physics import PHYSICS_VERSION
    from .golf.scenario import SCENARIO_VERSION

    return {
        "fly_golf": __version__,
        "protocol": PROTOCOL_VERSION,
        "physics": PHYSICS_VERSION,
        "course_physics": COURSE_PHYSICS_VERSION,
        "scenario": SCENARIO_VERSION,
        "course": COURSE_VERSION,
        "clubs": CLUBS_VERSION,
        "reward": REWARD_VERSION,
        "course_reward": COURSE_REWARD_VERSION,
        "sensory_mapping": SENSORY_MAPPING_VERSION_V2,
        "motor_mapping": MOTOR_MAPPING_VERSION_V2,
    }
