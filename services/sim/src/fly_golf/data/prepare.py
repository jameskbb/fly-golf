"""`make data` / `fly-golf-data`: acquire, verify and compile MaleCNS v1.0.

Commands:
    fly-golf-data status                  what exists and what is missing
    fly-golf-data prepare [--no-download] [--force]
                                          download (if needed), verify against the lock, compile
    fly-golf-data verify-source [--remote]
                                          hash the local files against the lock; with --remote
                                          also check the lock against the official bucket
    fly-golf-data lock [--write]          regenerate the lock from the official release

Compilation (the node and edge rules) lives in `compiler.py`; the lock in `lock.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from ..config import load_settings
from .compiler import COMPILED_FILES, COMPILER_VERSION, compile_release
from .lock import LockError, build_lock, validate_lock, verify_local, verify_remote

__all__ = ["COMPILED_FILES", "COMPILER_VERSION", "compiled_status", "load_lock", "main", "raw_status"]


def log(msg: str) -> None:
    print(f"[fly-golf-data] {msg}", file=sys.stderr, flush=True)


def load_lock(settings=None) -> dict:
    settings = settings or load_settings()
    return validate_lock(json.loads(settings.lock_path.read_text()))


def raw_status(settings=None) -> dict[str, str]:
    """Per-file status without hashing: missing | wrong_size | present."""
    settings = settings or load_settings()
    lock = load_lock(settings)
    out = {}
    for name, info in lock["files"].items():
        path = settings.raw_dir / name
        if not path.exists():
            out[name] = "missing"
        elif path.stat().st_size != info["bytes"]:
            out[name] = "wrong_size"
        else:
            out[name] = "present"
    return out


def compiled_status(settings=None) -> dict:
    settings = settings or load_settings()
    d = settings.compiled_dir
    missing = [f for f in COMPILED_FILES if not (d / f).exists()]
    manifest = None
    if not missing:
        try:
            manifest = json.loads((d / "manifest.json").read_text())
        except (OSError, json.JSONDecodeError):
            missing = ["manifest.json (unreadable)"]
    return {"ready": not missing, "missing": missing, "dir": str(d), "manifest": manifest}


def download(url: str, dest: Path, expected_bytes: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    log(f"downloading {url}\n    -> {dest} ({expected_bytes / 1e6:.1f} MB)")
    with urllib.request.urlopen(url) as response, partial.open("wb") as out:
        done, last = 0, time.time()
        while chunk := response.read(4 * 1024 * 1024):
            out.write(chunk)
            done += len(chunk)
            if time.time() - last > 5:
                log(f"    {done / 1e6:.0f}/{expected_bytes / 1e6:.0f} MB")
                last = time.time()
    partial.replace(dest)


def acquire(settings, allow_download: bool) -> None:
    """Make sure every locked source file is present and matches the lock byte for byte."""
    lock = load_lock(settings)
    for name, info in lock["files"].items():
        path = settings.raw_dir / name
        if path.exists() and path.stat().st_size == info["bytes"]:
            continue
        if not allow_download:
            raise SystemExit(
                f"Missing {path}. Download it with:\n  curl -L -o '{path}' '{info['url']}'\n"
                "or re-run without --no-download."
            )
        download(info["url"], path, info["bytes"])
    log("verifying sha256 of every source file ...")
    status = verify_local(lock, settings.raw_dir)
    bad = {k: v for k, v in status.items() if v != "ok"}
    if bad:
        raise SystemExit(
            f"Source files do not match {settings.lock_path.name}: {bad}\n"
            "Delete the files listed and re-run to download them again."
        )
    log(f"all source files verified against {settings.lock_path.name}")


def cmd_status() -> int:
    s = load_settings()
    lock = load_lock(s)
    print(f"MaleCNS v1.0 raw files in {s.raw_dir}:")
    for name, st in raw_status(s).items():
        mark = "OK " if st == "present" else "!! "
        print(f"  {mark}{name:28s} {st}  ({lock['files'][name]['bytes'] / 1e6:.1f} MB)")
    c = compiled_status(s)
    if c["ready"]:
        m = c["manifest"]
        stale = "" if m.get("compiler_version") == COMPILER_VERSION else f" (compiled by {m.get('compiler_version')})"
        print(f"Compiled graph: READY in {c['dir']} ({m['neurons']:,} neurons, {m['edges']:,} edges){stale}")
        return 0
    print(f"Compiled graph: NOT READY in {c['dir']} (missing: {', '.join(c['missing'])})")
    print("Run `make data` (or `uv run fly-golf-data prepare`) to download (~1.1 GB, CC BY 4.0) and compile.")
    return 1


def cmd_verify_source(remote: bool) -> int:
    s = load_settings()
    lock = load_lock(s)
    ok = True
    for name, st in verify_local(lock, s.raw_dir).items():
        ok &= st == "ok"
        print(f"  local  {name:28s} {st}")
    if remote:
        for name, st in verify_remote(lock).items():
            ok &= st == "ok"
            print(f"  remote {name:28s} {st}")
    print("source files verified" if ok else "SOURCE VERIFICATION FAILED")
    return 0 if ok else 2


def cmd_lock(write: bool) -> int:
    """Regenerate the lock: official metadata check, local SHA-256, and a fresh compile (into a
    temporary directory) to record the counts Fly Golf's compiler produces."""
    s = load_settings()
    old = json.loads(s.lock_path.read_text()) if s.lock_path.exists() else {}
    draft = build_lock(s.raw_dir, expected_compiled=None)
    with tempfile.TemporaryDirectory(prefix="fly-golf-lock-") as tmp:
        m = compile_release(s.raw_dir, Path(tmp), draft, log=log)
    lock = draft | {
        "expected_compiled": {
            "neurons": m["neurons"],
            "edges": m["edges"],
            "synaptic_contacts": m["synaptic_contacts"],
            "compiler_version": COMPILER_VERSION,
        }
    }
    text = json.dumps(lock, indent=2) + "\n"
    changed = {
        name: info["sha256"] != (old.get("files", {}).get(name) or {}).get("sha256")
        for name, info in lock["files"].items()
    }
    print(text)
    print(f"digests changed vs current lock: {changed}")
    if write:
        s.lock_path.write_text(text)
        print(f"wrote {s.lock_path}")
    else:
        print("(dry run: pass --write to replace the lock)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fly-golf-data", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="report which artifacts exist")
    p = sub.add_parser("prepare", help="download, verify and compile MaleCNS v1.0")
    p.add_argument("--no-download", action="store_true", help="fail instead of downloading missing files")
    p.add_argument("--force", action="store_true", help="recompile even if a compiled graph exists")
    v = sub.add_parser("verify-source", help="check local source files against the lock")
    v.add_argument("--remote", action="store_true", help="also check the lock against the official bucket")
    lk = sub.add_parser("lock", help="regenerate the lock from the official release")
    lk.add_argument("--write", action="store_true", help="replace data/malecns_v1.lock.json")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            return cmd_status()
        if args.cmd == "verify-source":
            return cmd_verify_source(args.remote)
        if args.cmd == "lock":
            return cmd_lock(args.write)
        s = load_settings()
        if compiled_status(s)["ready"] and not args.force:
            log("compiled graph already present (use --force to rebuild)")
            return cmd_status()
        acquire(s, allow_download=not args.no_download)
        manifest = compile_release(s.raw_dir, s.compiled_dir, load_lock(s), log=log)
        if not all(manifest["matches_expected"].values()):
            log(f"WARNING: counts differ from the lock's expectations: {manifest['matches_expected']}")
        return cmd_status()
    except LockError as exc:
        print(f"lock error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
