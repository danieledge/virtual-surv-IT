"""Tests for the ADR-014 guard-daemon design spike (docs/internal/adr-014-spike/).

NOT testing production code - guard_daemon.py / guard_daemon_client.py are a spike,
not wired into any live hook path (.claude/hooks/run-guard.sh is untouched by their
existence). These tests cover the pure-logic pieces (mtime comparison, port-file
read/write, client fallback decisions) with real isolation. The genuinely
execution-dependent behaviour - does a real daemon process actually start, serve
concurrent connections correctly, detect staleness, and idle-timeout in practice -
is NOT covered here; that needs a live run, not a mock, and is what
docs/internal/adr-014-spike/smoke_test.sh is for. Written but not executed by the
model that authored it (execution-consent gate, CLAUDE.md §7) - run before treating
this as more than syntax/lint-verified.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPIKE_DIR = REPO_ROOT / "docs" / "internal" / "adr-014-spike"

pytestmark = pytest.mark.skipif(not SPIKE_DIR.is_dir(), reason="ADR-014 spike not present")


def _load_spike_guard_daemon(monkeypatch):
    """Load docs/internal/adr-014-spike/guard_daemon.py by explicit file path,
    immune to sys.path ordering.

    This file used to do `sys.path.insert(0, str(SPIKE_DIR))` once at module level,
    then a bare `import guard_daemon` inside each test. That only works if SPIKE_DIR
    is still at the FRONT of sys.path when the test actually RUNS, not just when this
    file is collected - and another test file's own module-level sys.path.insert(0,
    ...) can silently win that race. Confirmed reproducible, 2026-08-12:
    tests/test_stop_hook_dispatcher.py inserts scripts/staged_hooks/ at position 0
    during ITS OWN collection, which happens AFTER this file's (alphabetically later
    filename) - so by the time a test function here executed `import guard_daemon`,
    scripts/staged_hooks/ was ahead of SPIKE_DIR, and Python silently imported the
    PRODUCTION guard_daemon.py (a different, evolving API missing read_port) instead
    of the spike's own. Passed standalone; failed only combined with that other file
    in the same test run - exactly the "looks healthy in isolation, silently wrong
    together" failure mode this project's own tests warn about elsewhere (see
    test_staged_matches_live's docstring on FCA Market Watch 79).

    Registered into sys.modules under the bare name "guard_daemon" (monkeypatch-
    scoped, auto-reverted after the test - never leaks into other tests) rather than
    just returned as a value, because guard_daemon_client.py's own top-level
    `from guard_daemon import read_port` needs to find THIS exact instance when it is
    loaded next - sys.modules is checked before sys.path on every import, so
    pre-seeding it here makes that internal import collision-proof too."""
    path = SPIKE_DIR / "guard_daemon.py"
    spec = importlib.util.spec_from_file_location("guard_daemon", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon", module)
    spec.loader.exec_module(module)
    return module


def _load_spike_guard_daemon_client(monkeypatch):
    """Load docs/internal/adr-014-spike/guard_daemon_client.py the same way - loading
    guard_daemon first (see _load_spike_guard_daemon) so this module's own
    `from guard_daemon import read_port` resolves to the correct spike instance
    already sitting in sys.modules, not whatever sys.path would otherwise find."""
    _load_spike_guard_daemon(monkeypatch)
    path = SPIKE_DIR / "guard_daemon_client.py"
    spec = importlib.util.spec_from_file_location("guard_daemon_client", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon_client", module)
    spec.loader.exec_module(module)
    return module


def test_guard_module_paths_covers_the_same_six_files_the_dispatcher_checks(tmp_path, monkeypatch):
    gd = _load_spike_guard_daemon(monkeypatch)

    paths = gd._guard_module_paths(tmp_path)
    names = {p.name for p in paths}
    assert "bash_hook_dispatcher.py" in names
    assert "guard-raw-data.py" in names
    assert "guard-code-execution.py" in names
    assert "guard-consent-writes.py" in names
    assert "guard-findings-pack-write.py" in names
    assert "guard_daemon.py" in names  # a spike-code change must also trigger a restart


def test_mtimes_records_none_for_a_missing_file(tmp_path, monkeypatch):
    gd = _load_spike_guard_daemon(monkeypatch)

    missing = tmp_path / "does-not-exist.py"
    result = gd._mtimes([missing])
    assert result[str(missing)] is None


def test_mtimes_detects_a_real_change(tmp_path, monkeypatch):
    gd = _load_spike_guard_daemon(monkeypatch)

    f = tmp_path / "guard.py"
    f.write_text("v1", encoding="utf-8")
    before = gd._mtimes([f])
    f.write_text("v2", encoding="utf-8")
    # Some filesystems have coarse mtime resolution (as low as 1s on certain
    # setups) - bump the mtime explicitly rather than sleeping in a test, so
    # this can't flake on a fast filesystem where two writes land in the same
    # tick.
    import os

    st = f.stat()
    os.utime(f, (st.st_atime, st.st_mtime + 1))
    after = gd._mtimes([f])
    assert before != after


def test_read_port_none_when_file_absent(tmp_path, monkeypatch):
    gd = _load_spike_guard_daemon(monkeypatch)

    assert gd.read_port(tmp_path) is None


def test_read_port_none_on_corrupt_content(tmp_path, monkeypatch):
    """Fail-open, never crash a client over a half-written or corrupt port
    file - same posture as every other cache file in this project
    (.guard-interpreter, .guard-coldstart-ms)."""
    gd = _load_spike_guard_daemon(monkeypatch)

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("not-a-port", encoding="utf-8")
    assert gd.read_port(tmp_path) is None


def test_read_port_returns_the_written_value(tmp_path, monkeypatch):
    gd = _load_spike_guard_daemon(monkeypatch)

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("54321", encoding="utf-8")
    assert gd.read_port(tmp_path) == 54321


def test_client_falls_back_when_no_port_file(tmp_path, monkeypatch):
    """_try_daemon must return None (triggering the cold-start fallback path in
    main()) when there is no daemon to talk to - never raise, never hang."""
    client = _load_spike_guard_daemon_client(monkeypatch)

    assert client._try_daemon(tmp_path, '{"tool_name": "Read"}') is None


def test_client_falls_back_when_connection_refused(tmp_path, monkeypatch):
    """A port file pointing at a port nothing is listening on (a crashed daemon
    that didn't clean up) must fall back cleanly, not raise."""
    client = _load_spike_guard_daemon_client(monkeypatch)

    (tmp_path / ".claude").mkdir()
    # Port 1 is privileged/unlikely-bound on any dev box - connection refused
    # is the expected, fast failure mode this exercises.
    (tmp_path / ".claude" / "guard-daemon-port-unused-name").write_text("1", encoding="utf-8")
    monkeypatch.setattr(client, "read_port", lambda _root: 1)
    assert client._try_daemon(tmp_path, '{"tool_name": "Read"}') is None


def test_cold_start_fallback_runs_the_real_dispatcher_on_a_harmless_payload(monkeypatch):
    """The fallback path must still produce a correct, non-crashing result on a
    harmless payload - proves the fallback itself is wired to the real
    dispatcher script, not a stub."""
    client = _load_spike_guard_daemon_client(monkeypatch)

    exit_code, stderr_text = client._cold_start_fallback(
        REPO_ROOT, '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}'
    )
    assert exit_code == 0
    assert stderr_text == ""
