"""Tests for the production guard daemon (scripts/staged_hooks/guard_daemon.py,
scripts/staged_hooks/guard_daemon_client.py) - promoted from the ADR-014 design
spike (see tests/test_adr014_guard_daemon_spike.py, which tests the now-archived
spike copy, not this one). No test file covered the production module directly
before this one - a gap the 2026-08-13 audit noted.

Tests the STAGED copies (same convention as tests/test_run_guard_interpreter_cache.py's
LAUNCHER constant) - functional correctness is verified here; a separate byte-identity
check (test_hooks_in_sync.py's test_staged_matches_live) enforces that a human has
applied staged to live before treating a fix as actually deployed.

Focus: the 2026-08-13 fix for the module_root/state_root conflation - a live audit
caught that guard_daemon.py and guard_daemon_client.py used ONE root for two
different things (locating the plugin-shipped dispatcher vs. this project's own
port file), the same bug class run-guard.sh's own $_root/$_project_root split had
already fixed one layer up. These tests exist specifically to make that conflation
impossible to silently reintroduce.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGED_DIR = REPO_ROOT / "scripts" / "staged_hooks"


def _load_guard_daemon(monkeypatch):
    """Load scripts/staged_hooks/guard_daemon.py by explicit file path, registered
    into sys.modules under the bare name "guard_daemon" so guard_daemon_client.py's
    own `from guard_daemon import read_port_and_token` resolves to THIS instance -
    same collision-proofing rationale as the spike test file's loader (see its
    docstring: two same-named modules on sys.path is a real, previously-hit bug)."""
    path = STAGED_DIR / "guard_daemon.py"
    spec = importlib.util.spec_from_file_location("guard_daemon", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon", module)
    spec.loader.exec_module(module)
    return module


def _load_guard_daemon_client(monkeypatch):
    _load_guard_daemon(monkeypatch)
    path = STAGED_DIR / "guard_daemon_client.py"
    spec = importlib.util.spec_from_file_location("guard_daemon_client", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon_client", module)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------- read_port_and_token


def test_read_port_and_token_none_when_file_absent(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    assert gd.read_port_and_token(tmp_path) == (None, None)


def test_read_port_and_token_none_on_corrupt_content(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("garbage", encoding="utf-8")
    assert gd.read_port_and_token(tmp_path) == (None, None)


def test_read_port_and_token_returns_written_values(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("54321\nabc123\n", encoding="utf-8")
    assert gd.read_port_and_token(tmp_path) == (54321, "abc123")


# --------------------------------------------------------------- run(): the actual fix


def test_run_writes_port_file_under_state_root_not_module_root(tmp_path, monkeypatch):
    """The regression this whole fix exists for, reproduced directly: a REAL daemon
    process, started with module_root != state_root, must place its port file under
    state_root - never module_root."""
    gd = _load_guard_daemon(monkeypatch)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    module_root.mkdir()
    state_root.mkdir()

    result = {}

    def _run():
        result["code"] = gd.run(module_root, state_root, idle_timeout=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 10
        port_file = state_root / ".claude" / gd.PORT_FILE_NAME
        while time.monotonic() < deadline and not port_file.is_file():
            time.sleep(0.05)
        assert port_file.is_file(), "port file never appeared under state_root"
        assert not (module_root / ".claude").exists(), (
            "port file (or its parent dir) leaked under module_root"
        )
        port, token = gd.read_port_and_token(state_root)
        assert port is not None and token
    finally:
        t.join(timeout=5)


def test_run_defaults_state_root_to_module_root_when_omitted(tmp_path, monkeypatch):
    """Backward compatibility: a caller that still passes only one root (today's
    project-mode invocation) keeps writing the port file where it always did."""
    gd = _load_guard_daemon(monkeypatch)

    result = {}

    def _run():
        result["code"] = gd.run(tmp_path, idle_timeout=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 10
        port_file = tmp_path / ".claude" / gd.PORT_FILE_NAME
        while time.monotonic() < deadline and not port_file.is_file():
            time.sleep(0.05)
        assert port_file.is_file()
    finally:
        t.join(timeout=5)


# --------------------------------------------------------------- client: state vs module root


def test_client_try_daemon_reads_port_from_state_root(tmp_path, monkeypatch):
    client = _load_guard_daemon_client(monkeypatch)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    module_root.mkdir()
    (state_root / ".claude").mkdir(parents=True)
    # Port 1 is privileged/unlikely-bound - connection refused is the fast,
    # deterministic failure this exercises (same technique as the spike test).
    (state_root / ".claude" / "guard-daemon-port").write_text("1\ndeadbeef\n", encoding="utf-8")

    assert client._try_daemon(state_root, '{"tool_name": "Read"}') is None
    # Never looked under module_root at all.
    assert not (module_root / ".claude").exists()


def test_client_cold_start_fallback_uses_module_root_for_the_real_dispatcher(monkeypatch):
    """The fallback must find the REAL, plugin-shipped dispatcher via module_root -
    proven by pointing module_root at the actual repo root and getting a real,
    correct (non-error) result back."""
    client = _load_guard_daemon_client(monkeypatch)

    exit_code, _stderr = client._cold_start_fallback(
        REPO_ROOT, '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}'
    )
    assert exit_code == 0


def test_client_start_daemon_detached_passes_both_roots_to_the_subprocess(tmp_path, monkeypatch):
    """The actual regression, one layer up: the spawned daemon subprocess must
    receive BOTH module_root and state_root as separate argv entries, not
    collapsed into one."""
    client = _load_guard_daemon_client(monkeypatch)

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv

        class _P:
            pass

        return _P()

    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    client._start_daemon_detached(module_root, state_root)

    assert captured["argv"][-2:] == [str(module_root), str(state_root)]


def test_client_windows_spawn_sets_breakaway_from_job(tmp_path, monkeypatch):
    """2026-08-13 (reported via log analysis of a real session): DETACHED_PROCESS and
    CREATE_NO_WINDOW control console inheritance, NOT Windows Job Object membership - a
    child is still added to the SAME job as its parent by default regardless of those two
    flags. Many terminal/IDE launchers put their process tree in a job with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, which would silently kill this "detached" daemon
    the moment the invoking session ends - defeating the entire point of a persistent
    daemon. CREATE_BREAKAWAY_FROM_JOB must be set alongside the other two.

    None of the three creationflags constants exist as real subprocess module attributes
    on non-Windows Python (confirmed: hasattr is False for all three on this Linux box) -
    injected here (raising=False) so this test can exercise the Windows branch on any
    platform, same technique tests elsewhere in this project already use for OS-specific
    code paths."""
    client = _load_guard_daemon_client(monkeypatch)

    monkeypatch.setattr(client.sys, "platform", "win32")
    monkeypatch.setattr(client.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(client.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(client.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["kwargs"] = kwargs

        class _P:
            pass

        return _P()

    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)
    client._start_daemon_detached(tmp_path / "plugin-install", tmp_path / "project")

    flags = captured["kwargs"]["creationflags"]
    assert flags & 0x00000008  # DETACHED_PROCESS
    assert flags & 0x08000000  # CREATE_NO_WINDOW
    assert flags & 0x01000000  # CREATE_BREAKAWAY_FROM_JOB - the actual fix


def test_client_main_defaults_state_root_to_module_root_with_one_arg(tmp_path, monkeypatch):
    """CLI backward compatibility: `guard_daemon_client.py <module_root>` alone
    (today's call shape from an unmodified run-guard.sh, or any other caller that
    hasn't been updated) must still behave exactly as before - state_root falls
    back to module_root."""
    client = _load_guard_daemon_client(monkeypatch)

    seen = {}

    def fake_try_daemon(state_root, payload_text):
        seen["state_root"] = state_root
        return (0, "")

    monkeypatch.setattr(client, "_try_daemon", fake_try_daemon)
    monkeypatch.setattr(sys, "argv", ["guard_daemon_client.py", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))

    client.main()
    assert seen["state_root"] == tmp_path


# --------------------------------------------------------------- run-guard.sh integration


LAUNCHER = STAGED_DIR / "run-guard.sh"

pytestmark_sh = pytest.mark.skipif(
    sys.platform == "win32" or not LAUNCHER.is_file(),
    reason="needs a POSIX shell + staged launcher",
)


@pytestmark_sh
def test_launcher_invokes_daemon_client_with_both_roots_when_they_differ(tmp_path):
    """End-to-end proof at the run-guard.sh level: with CLAUDE_PLUGIN_ROOT and
    CLAUDE_PROJECT_DIR pointing at two DIFFERENT directories, and guard_daemon
    true, the launcher must invoke DAEMON_CLIENT with BOTH roots as distinct
    positional args, in ($_root, $_project_root) order."""
    import json
    import os

    plugin_root = tmp_path / "plugin-install"
    project_dir = tmp_path / "project"
    (plugin_root / "scripts").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    (project_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    dispatcher_target = project_dir / "bash_hook_dispatcher.py"
    dispatcher_target.write_text("", encoding="utf-8")

    argv_log = plugin_root / "argv.log"
    fake_client = plugin_root / "scripts" / "guard_daemon_client.py"
    fake_client.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_client.chmod(0o755)

    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "PATH": os.environ["PATH"],
    }
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})
    proc = subprocess.run(
        ["sh", str(LAUNCHER), str(dispatcher_target)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert argv_log.is_file(), "the fake daemon client was never invoked"
    lines = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"expected exactly 2 args (module_root, state_root), got {lines}"
    assert lines[0] == str(plugin_root)
    assert lines[1] == str(project_dir)


@pytestmark_sh
def test_launcher_self_locates_when_claude_plugin_root_is_unset(tmp_path):
    """The exact reported live scenario: CLAUDE_PLUGIN_ROOT is completely UNSET in this
    process (not just pointing somewhere unexpected - genuinely absent, as when Claude
    Code's hook templating substitutes it correctly into the command line but doesn't
    also export it into the spawned process's environment). Without self-location, $_root
    falls back to CLAUDE_PROJECT_DIR, and DAEMON_CLIENT resolves to
    <project>/scripts/guard_daemon_client.py - a file that only ever lives in the
    plugin's own tree, never copied into a consuming project - so the daemon silently
    never engages. The launcher is placed at its real, documented location
    (.claude/hooks/run-guard.sh under a fake plugin root) and invoked by that literal
    path, exactly as Claude Code's own templating would construct the command - proving
    $0-based self-location recovers the correct root even with the env var entirely
    missing."""
    import json
    import os
    import shutil

    plugin_root = tmp_path / "plugin-install"
    project_dir = tmp_path / "project"
    (plugin_root / "scripts").mkdir(parents=True)
    hooks_dir = plugin_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    shutil.copy2(LAUNCHER, hooks_dir / "run-guard.sh")
    (project_dir / ".claude").mkdir(parents=True)
    (project_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    dispatcher_target = project_dir / "bash_hook_dispatcher.py"
    dispatcher_target.write_text("", encoding="utf-8")

    argv_log = plugin_root / "argv.log"
    fake_client = plugin_root / "scripts" / "guard_daemon_client.py"
    fake_client.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_client.chmod(0o755)

    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        # CLAUDE_PLUGIN_ROOT deliberately absent - the exact reported failure condition.
        "PATH": os.environ["PATH"],
    }
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})
    proc = subprocess.run(
        ["sh", str(hooks_dir / "run-guard.sh"), str(dispatcher_target)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert argv_log.is_file(), (
        "the fake daemon client was never invoked - self-location did not recover the plugin root"
    )
    lines = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == str(plugin_root), (
        f"module_root resolved to {lines[0]!r}, expected the plugin root {str(plugin_root)!r} "
        "- self-location fell back to something else"
    )
    assert lines[1] == str(project_dir)
