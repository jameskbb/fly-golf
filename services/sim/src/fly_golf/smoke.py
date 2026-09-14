"""Startup smoke test: boot the real uvicorn server, hit /health and /api/status, shut down.

Used by CI (`make smoke`) and safe to run locally. Needs no connectome data.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    env = dict(os.environ)
    env.setdefault("FLY_GOLF_RUNS_DIR", os.path.join(os.getcwd(), ".smoke-runs"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fly_golf.api.app:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    health = json.loads(r.read())
                    break
            except OSError:
                time.sleep(0.3)
        else:
            print("smoke: server did not become healthy", file=sys.stderr)
            return 1
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            status = json.loads(r.read())
        assert health["status"] == "ok", health
        assert status["active_controller"] == "mock", status
        print(
            f"smoke OK: {health['service']} v{health['version']} protocol {health['protocol_version']}; "
            f"malecns={status['malecns']['status']}"
        )
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
