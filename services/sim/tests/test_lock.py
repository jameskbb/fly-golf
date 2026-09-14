"""The MaleCNS source lock: validation, local verification, and generation against (mocked)
official object metadata. No network access."""

from __future__ import annotations

import copy
import json

import pytest

from fly_golf.config import load_settings
from fly_golf.data import prepare
from fly_golf.data.lock import (
    OFFICIAL_BASE,
    SOURCE_FILES,
    LockError,
    build_lock,
    file_digests,
    validate_lock,
    verify_local,
    verify_remote,
)


@pytest.fixture
def raw(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    for i, name in enumerate(SOURCE_FILES):
        (d / name).write_bytes(bytes(range(256)) * (i + 3))
    return d


def official(raw, **override):
    """A fake release bucket whose objects are exactly the files in `raw`."""

    def fetch(url):
        name = next(n for n, f in SOURCE_FILES.items() if url.endswith(f))
        d = file_digests(raw / name)
        return {"bytes": d["bytes"], "md5": d["md5"], "generation": "1", "last_modified": "x"} | override.get(name, {})

    return fetch


def test_build_lock_records_official_urls_and_local_digests(raw):
    lock = build_lock(raw, {"neurons": 3}, fetch=official(raw))
    assert set(lock["files"]) == set(SOURCE_FILES)
    for name, info in lock["files"].items():
        assert info["url"] == f"{OFFICIAL_BASE}/{SOURCE_FILES[name]}"
        d = file_digests(raw / name)
        assert (info["bytes"], info["sha256"], info["md5"]) == (d["bytes"], d["sha256"], d["md5"])
    assert lock["generated_by"] == "fly-golf-data lock"
    assert lock["expected_compiled"] == {"neurons": 3}
    assert "doomfly" not in json.dumps(lock).lower()
    assert verify_local(lock, raw) == dict.fromkeys(SOURCE_FILES, "ok")
    assert verify_remote(lock, fetch=official(raw)) == dict.fromkeys(SOURCE_FILES, "ok")


def test_build_lock_refuses_a_file_that_is_not_the_official_object(raw):
    with pytest.raises(LockError, match="MD5"):
        build_lock(raw, None, fetch=official(raw, **{"edges.feather": {"md5": "0" * 32}}))
    with pytest.raises(LockError, match="bytes"):
        build_lock(raw, None, fetch=official(raw, **{"annotations.feather": {"bytes": 1}}))
    with pytest.raises(LockError, match="no MD5"):
        build_lock(raw, None, fetch=official(raw, **{"annotations.feather": {"md5": None}}))
    (raw / "edges.feather").unlink()
    with pytest.raises(LockError, match="missing"):
        build_lock(raw, None, fetch=official(raw))


def test_checksum_and_size_mismatches_fail_verification(raw):
    lock = build_lock(raw, None, fetch=official(raw))
    data = bytearray((raw / "edges.feather").read_bytes())
    data[10] ^= 0xFF  # same size, different content
    (raw / "edges.feather").write_bytes(bytes(data))
    (raw / "annotations.feather").write_bytes(b"short")
    (raw / "neurotransmitters.feather").unlink()
    assert verify_local(lock, raw) == {
        "annotations.feather": "wrong_size",
        "neurotransmitters.feather": "missing",
        "edges.feather": "sha256_mismatch",
    }


def test_remote_changes_are_detected(raw):
    lock = build_lock(raw, None, fetch=official(raw))
    moved = official(raw, **{"edges.feather": {"md5": "f" * 32}, "annotations.feather": {"bytes": 7}})
    assert verify_remote(lock, fetch=moved) == {
        "annotations.feather": "size_mismatch",
        "neurotransmitters.feather": "ok",
        "edges.feather": "md5_mismatch",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("files"),
        lambda d: d.pop("dataset"),
        lambda d: d["files"].pop("edges.feather"),
        lambda d: d["files"].__setitem__("extra.feather", d["files"]["edges.feather"]),
        lambda d: d["files"]["edges.feather"].__setitem__("sha256", "abc"),
        lambda d: d["files"]["edges.feather"].__setitem__("sha256", "G" * 64),
        lambda d: d["files"]["edges.feather"].__setitem__("bytes", 0),
        lambda d: d["files"]["edges.feather"].__setitem__("bytes", "12"),
        lambda d: d["files"]["edges.feather"].__setitem__("url", "http://insecure/x"),
        lambda d: d["files"]["edges.feather"].__setitem__("md5", "xyz"),
    ],
)
def test_malformed_locks_are_rejected(raw, mutate):
    lock = copy.deepcopy(build_lock(raw, None, fetch=official(raw)))
    mutate(lock)
    with pytest.raises(LockError):
        validate_lock(lock)


def test_acquire_refuses_mismatched_files(raw, tmp_path, monkeypatch):
    lock = build_lock(raw, None, fetch=official(raw))
    lock_path = tmp_path / "data" / "malecns_v1.lock.json"
    lock_path.parent.mkdir()
    lock_path.write_text(json.dumps(lock))
    (tmp_path / "data" / "raw").mkdir()
    (raw).rename(tmp_path / "data" / "raw" / "malecns_v1")
    monkeypatch.setenv("FLY_GOLF_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("FLY_GOLF_DATA_DIR", raising=False)  # a developer's real data dir must not leak in
    s = load_settings()
    prepare.acquire(s, allow_download=False)  # everything matches
    target = s.raw_dir / "neurotransmitters.feather"
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    target.write_bytes(bytes(data))
    with pytest.raises(SystemExit, match="do not match"):
        prepare.acquire(s, allow_download=False)


def test_committed_lock_is_valid_and_fly_golf_generated():
    lock = json.loads(load_settings().lock_path.read_text())
    validate_lock(lock)
    assert lock["generated_by"] == "fly-golf-data lock"
    assert lock["release"] == "MaleCNS v1.0" and lock["license"] == "CC BY 4.0"
    for name, info in lock["files"].items():
        assert info["url"] == f"{OFFICIAL_BASE}/{SOURCE_FILES[name]}"
        assert "md5" in info
