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

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPIKE_DIR = REPO_ROOT / "docs" / "internal" / "adr-014-spike"

pytestmark = pytest.mark.skipif(not SPIKE_DIR.is_dir(), reason="ADR-014 spike not present")

if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))


def test_guard_module_paths_covers_the_same_six_files_the_dispatcher_checks(tmp_path):
    import guard_daemon as gd

    paths = gd._guard_module_paths(tmp_path)
    names = {p.name for p in paths}
    assert "bash_hook_dispatcher.py" in names
    assert "guard-raw-data.py" in names
    assert "guard-code-execution.py" in names
    assert "guard-consent-writes.py" in names
    assert "guard-findings-pack-write.py" in names
    assert "guard_daemon.py" in names  # a spike-code change must also trigger a restart


def test_mtimes_records_none_for_a_missing_file(tmp_path):
    import guard_daemon as gd

    missing = tmp_path / "does-not-exist.py"
    result = gd._mtimes([missing])
    assert result[str(missing)] is None


def test_mtimes_detects_a_real_change(tmp_path):
    import guard_daemon as gd

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


def test_read_port_none_when_file_absent(tmp_path):
    import guard_daemon as gd

    assert gd.read_port(tmp_path) is None


def test_read_port_none_on_corrupt_content(tmp_path):
    """Fail-open, never crash a client over a half-written or corrupt port
    file - same posture as every other cache file in this project
    (.guard-interpreter, .guard-coldstart-ms)."""
    import guard_daemon as gd

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("not-a-port", encoding="utf-8")
    assert gd.read_port(tmp_path) is None


def test_read_port_returns_the_written_value(tmp_path):
    import guard_daemon as gd

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("54321", encoding="utf-8")
    assert gd.read_port(tmp_path) == 54321


def test_client_falls_back_when_no_port_file(tmp_path, monkeypatch):
    """_try_daemon must return None (triggering the cold-start fallback path in
    main()) when there is no daemon to talk to - never raise, never hang."""
    import guard_daemon_client as client

    assert client._try_daemon(tmp_path, '{"tool_name": "Read"}') is None


def test_client_falls_back_when_connection_refused(tmp_path, monkeypatch):
    """A port file pointing at a port nothing is listening on (a crashed daemon
    that didn't clean up) must fall back cleanly, not raise."""
    import guard_daemon_client as client

    (tmp_path / ".claude").mkdir()
    # Port 1 is privileged/unlikely-bound on any dev box - connection refused
    # is the expected, fast failure mode this exercises.
    (tmp_path / ".claude" / "guard-daemon-port-unused-name").write_text("1", encoding="utf-8")
    monkeypatch.setattr(client, "read_port", lambda _root: 1)
    assert client._try_daemon(tmp_path, '{"tool_name": "Read"}') is None


def test_cold_start_fallback_runs_the_real_dispatcher_on_a_harmless_payload():
    """The fallback path must still produce a correct, non-crashing result on a
    harmless payload - proves the fallback itself is wired to the real
    dispatcher script, not a stub."""
    import guard_daemon_client as client

    exit_code, stderr_text = client._cold_start_fallback(
        REPO_ROOT, '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}'
    )
    assert exit_code == 0
    assert stderr_text == ""
