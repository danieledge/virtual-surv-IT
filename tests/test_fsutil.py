"""Tests for scripts/fsutil.py (2026-09-12 test-quality audit).

The module's whole point is a contract: readers never see a half-written file, a failed
write leaves the original untouched, and a transient Windows "file in use" is retried
rather than failing a write that would have succeeded moments later. These tests pin that
contract directly - including with real concurrent writers, not just a mocked race - plus
the ordinary read/write round-trip every caller actually depends on.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

import scripts.fsutil as fsutil


# ------------------------------------------------------------------ basic round-trip


def test_atomic_write_text_then_read_back(tmp_path):
    target = tmp_path / "note.txt"
    fsutil.atomic_write_text(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"


def test_atomic_write_text_creates_missing_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c" / "note.txt"
    fsutil.atomic_write_text(target, "nested")
    assert target.read_text(encoding="utf-8") == "nested"


def test_atomic_write_text_always_uses_utf8_by_default(tmp_path):
    target = tmp_path / "note.txt"
    fsutil.atomic_write_text(target, "café ☃")
    assert target.read_text(encoding="utf-8") == "café ☃"


def test_atomic_write_text_leaves_no_tmp_sibling_behind(tmp_path):
    target = tmp_path / "note.txt"
    fsutil.atomic_write_text(target, "hello")
    leftovers = [p for p in tmp_path.iterdir() if p.name != "note.txt"]
    assert leftovers == []


def test_atomic_write_json_round_trips(tmp_path):
    target = tmp_path / "state.json"
    obj = {"b": 1, "a": 2, "nested": {"x": [1, 2, 3]}}
    fsutil.atomic_write_json(target, obj)
    assert fsutil.read_json(target) == obj


def test_atomic_write_json_default_shape_is_indented_with_trailing_newline(tmp_path):
    target = tmp_path / "state.json"
    fsutil.atomic_write_json(target, {"a": 1})
    raw = target.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "  " in raw  # indent=2


def test_atomic_write_json_keeps_non_ascii_as_is_not_escaped(tmp_path):
    target = tmp_path / "state.json"
    fsutil.atomic_write_json(target, {"name": "café"})
    raw = target.read_text(encoding="utf-8")
    assert "café" in raw
    assert "\\u00e9" not in raw


def test_atomic_write_json_sort_keys_when_asked(tmp_path):
    target = tmp_path / "state.json"
    fsutil.atomic_write_json(target, {"b": 1, "a": 2}, sort_keys=True)
    raw = target.read_text(encoding="utf-8")
    assert raw.index('"a"') < raw.index('"b"')


# ------------------------------------------------------------------ read_json


def test_read_json_missing_file_returns_the_default(tmp_path):
    assert fsutil.read_json(tmp_path / "nope.json") is None
    sentinel = {"x": 1}
    assert fsutil.read_json(tmp_path / "nope.json", default=sentinel) is sentinel


def test_read_json_corrupt_file_raises_rather_than_reading_as_empty(tmp_path):
    """S-17/W-10: silently treating corruption as 'empty' is how a broken control looks
    healthy. A present-but-corrupt file must raise, not return the default."""
    target = tmp_path / "state.json"
    target.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        fsutil.read_json(target)


# ------------------------------------------------------------------ failure cleanup


def test_a_write_that_fails_mid_flight_leaves_the_original_untouched(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    fsutil.atomic_write_text(target, "original")

    def _boom(*_a, **_k):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(OSError):
        fsutil.atomic_write_text(target, "new content that must never land")

    assert target.read_text(encoding="utf-8") == "original"


def test_a_failed_write_removes_its_own_tmp_file(tmp_path, monkeypatch):
    target = tmp_path / "state.json"

    def _boom(*_a, **_k):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(OSError):
        fsutil.atomic_write_text(target, "never lands")

    # No target (first write ever), and no stray .tmp sibling either.
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_write_that_fails_when_the_target_never_existed_leaves_nothing(tmp_path, monkeypatch):
    target = tmp_path / "state.json"

    def _boom(tmp, dest):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(fsutil, "_replace_with_retry", _boom)
    with pytest.raises(OSError):
        fsutil.atomic_write_text(target, "never lands")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ the Windows retry path


class _NoSleep:
    """Stand-in for the `time` module so retry tests don't pay the real backoff delay."""

    def sleep(self, _seconds):
        return None


def test_replace_with_retry_succeeds_past_transient_permission_errors(tmp_path, monkeypatch):
    tmp = tmp_path / ".target.123.abcd.tmp"
    tmp.write_text("payload", encoding="utf-8")
    target = tmp_path / "target"

    calls = {"n": 0}
    real_replace = os.replace

    def _flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("simulated: file in use")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky_replace)
    monkeypatch.setattr(fsutil, "time", _NoSleep())

    fsutil._replace_with_retry(tmp, target)
    assert target.read_text(encoding="utf-8") == "payload"
    assert calls["n"] == 3


def test_replace_with_retry_gives_up_after_the_attempt_budget(tmp_path, monkeypatch):
    tmp = tmp_path / ".target.123.abcd.tmp"
    tmp.write_text("payload", encoding="utf-8")
    target = tmp_path / "target"

    def _always_locked(src, dst):
        raise PermissionError("simulated: file always in use")

    monkeypatch.setattr(os, "replace", _always_locked)
    monkeypatch.setattr(fsutil, "time", _NoSleep())

    with pytest.raises(PermissionError):
        fsutil._replace_with_retry(tmp, target)


def test_atomic_write_text_survives_a_transient_permission_error_on_replace(tmp_path, monkeypatch):
    """The end-to-end path: atomic_write_text must retry through os.replace's own
    PermissionError, not just the isolated _replace_with_retry unit above."""
    target = tmp_path / "state.json"
    fsutil.atomic_write_text(target, "old")

    calls = {"n": 0}
    real_replace = os.replace

    def _flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 2:
            raise PermissionError("simulated: file in use")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky_replace)
    monkeypatch.setattr(fsutil, "time", _NoSleep())

    fsutil.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


# ------------------------------------------------------------------ unlink_quietly


def test_unlink_quietly_removes_an_existing_file(tmp_path):
    f = tmp_path / "marker"
    f.write_text("x", encoding="utf-8")
    assert fsutil.unlink_quietly(f) is True
    assert not f.exists()


def test_unlink_quietly_on_a_missing_file_is_true_not_an_error(tmp_path):
    assert fsutil.unlink_quietly(tmp_path / "never-existed") is True


def test_unlink_quietly_retries_past_a_transient_permission_error(tmp_path, monkeypatch):
    f = tmp_path / "marker"
    f.write_text("x", encoding="utf-8")

    calls = {"n": 0}
    real_unlink = Path.unlink

    def _flaky_unlink(self, missing_ok=False):
        calls["n"] += 1
        if calls["n"] < 2:
            raise PermissionError("simulated: file in use")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _flaky_unlink)
    monkeypatch.setattr(fsutil, "time", _NoSleep())

    assert fsutil.unlink_quietly(f) is True
    assert not f.exists()


def test_unlink_quietly_gives_up_and_reports_whether_it_is_gone(tmp_path, monkeypatch):
    f = tmp_path / "marker"
    f.write_text("x", encoding="utf-8")

    def _always_locked(self, missing_ok=False):
        raise PermissionError("simulated: file always in use")

    monkeypatch.setattr(Path, "unlink", _always_locked)
    monkeypatch.setattr(fsutil, "time", _NoSleep())

    assert fsutil.unlink_quietly(f) is False
    assert f.exists()


def test_unlink_quietly_never_raises_on_an_unexpected_oserror(tmp_path):
    """A directory can't be unlink()ed (IsADirectoryError, an OSError subclass) - the
    contract is "never raises", not "only tolerates the Windows case"."""
    d = tmp_path / "a_directory"
    d.mkdir()
    assert fsutil.unlink_quietly(d) is False
    assert d.exists()


# ------------------------------------------------------------------ _tmp_sibling


def test_tmp_sibling_is_hidden_and_named_after_the_target(tmp_path):
    target = tmp_path / "state.json"
    tmp = fsutil._tmp_sibling(target)
    assert tmp.parent == target.parent
    assert tmp.name.startswith(".state.json.")
    assert tmp.name.endswith(".tmp")


def test_tmp_sibling_is_unique_on_every_call():
    target = Path("state.json")
    names = {fsutil._tmp_sibling(target).name for _ in range(50)}
    assert len(names) == 50


# ------------------------------------------------------------------ concurrent writers


def test_concurrent_writers_never_produce_a_mixed_or_truncated_file(tmp_path):
    """The core atomicity claim: N threads hammering the SAME target concurrently must
    always leave a WHOLE write from exactly one of them, never a half-written mix - proven
    by parsing successfully (a torn write is not valid JSON) and by content just being one
    of the writers' own full payloads."""
    target = tmp_path / "shared.json"
    fsutil.atomic_write_json(target, {"writer": "seed", "n": -1})

    writers = 6
    rounds = 8
    barrier = threading.Barrier(writers)
    errors: list[BaseException] = []

    def _write(writer_id: int):
        try:
            barrier.wait()
            for n in range(rounds):
                fsutil.atomic_write_json(target, {"writer": writer_id, "n": n})
        except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert not any(t.is_alive() for t in threads)

    # Must parse (proves no torn/interleaved write reached the target) ...
    final = json.loads(target.read_text(encoding="utf-8"))
    # ... and must be exactly one writer's own last-known-consistent payload shape.
    assert set(final.keys()) == {"writer", "n"}
    assert final["writer"] in range(writers)
    assert 0 <= final["n"] < rounds

    # No writer's staging file survives - every thread either replaced cleanly or cleaned
    # up its own tmp on failure, and nothing here is expected to fail.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "shared.json"]
    assert leftovers == []


def test_concurrent_writers_to_different_targets_do_not_collide_on_tmp_names(tmp_path):
    """Two threads writing DIFFERENT files at the same instant must not race on a shared
    temp filename (the pid+random suffix is per-target, not merely per-process)."""
    targets = [tmp_path / f"file-{i}.json" for i in range(4)]
    barrier = threading.Barrier(len(targets))
    errors: list[BaseException] = []

    def _write(target: Path, idx: int):
        try:
            barrier.wait()
            for n in range(8):
                fsutil.atomic_write_json(target, {"idx": idx, "n": n})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(t, i)) for i, t in enumerate(targets)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    for i, target in enumerate(targets):
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["idx"] == i
        assert data["n"] == 7
