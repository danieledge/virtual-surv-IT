"""Interpreter cache in the guard launcher (scripts/staged_hooks/run-guard.sh, human-
installed via scripts/apply-guard-interpreter-cache.sh).

Regression under test (live corporate report 2026-07-30): "/engage takes several minutes".
Five PreToolUse hooks match Bash, and the launcher's interpreter-selection loop EXECUTES
each candidate (python3, python, py) to version-check it - not just checks it exists. On a
Windows box where python3.exe is the App Execution Alias stub (present via `command -v`,
but not a real interpreter), running it triggers a multi-second Microsoft Store redirect
check. That stub hang, repeated 5x per Bash call across a whole session, is what "several
minutes" was. The fix caches the first successfully version-checked interpreter to
.claude/.guard-interpreter and trusts it thereafter via cheap `command -v` existence checks
only - never re-executing it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "staged_hooks" / "run-guard.sh"
LIVE_LAUNCHER = REPO_ROOT / ".claude" / "hooks" / "run-guard.sh"
NOOP_TARGET = REPO_ROOT / ".claude" / "hooks" / "guard-raw-data.py"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="needs a POSIX shell"
)

PAYLOAD = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})


def _run(project_dir: Path):
    env = {"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": __import__("os").environ["PATH"]}
    return subprocess.run(
        ["sh", str(LAUNCHER), str(NOOP_TARGET)],
        input=PAYLOAD,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_first_call_writes_the_cache(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    assert _run(proj).returncode == 0
    cache = proj / ".claude" / ".guard-interpreter"
    assert cache.is_file()
    assert cache.read_text(encoding="utf-8").strip() in ("python3", "python", "py")


def test_second_call_reuses_the_cache_without_re_executing_others(tmp_path):
    """A cached interpreter that still resolves via `command -v` is exec'd directly - the
    probe-and-version-check loop must not run again."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    _run(proj)  # first call: writes the cache
    cache = proj / ".claude" / ".guard-interpreter"
    before = cache.read_text(encoding="utf-8")
    proc = _run(proj)
    assert proc.returncode == 0
    assert cache.read_text(encoding="utf-8") == before  # untouched by the cached path


def test_stale_cache_falls_back_to_the_full_probe(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / ".guard-interpreter").write_text(
        "definitely-not-a-real-interpreter", encoding="utf-8"
    )
    proc = _run(proj)
    assert proc.returncode == 0
    cache = proj / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8").strip() != "definitely-not-a-real-interpreter"


def test_guard_stdin_and_exit_code_pass_through_unchanged(tmp_path):
    """The cache must not change what the launcher actually does - stdin reaches the guard
    and its exit code (0 allow / 2 block) still passes through."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proc = _run(proj)
    assert proc.returncode == 0  # a harmless /tmp read is allowed


def _run_with_env(project_dir: Path, extra_env: dict, path_prefix: Path | None = None):
    import os

    path = str(path_prefix) + ":" + os.environ["PATH"] if path_prefix else os.environ["PATH"]
    env = {"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": path, **extra_env}
    return subprocess.run(
        ["sh", str(LAUNCHER), str(NOOP_TARGET)],
        input=PAYLOAD,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _fake_interpreter_bin_dir(tmp_path: Path) -> Path:
    """python3/python/py all copies of the REAL interpreter, so every candidate the
    launcher tries genuinely passes the version check and can exec the guard for real -
    which of the three gets cached then reveals the probe ORDER, not just correctness."""
    import shutil as _shutil

    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    real = Path(sys.executable)
    for name in ("python3", "python", "py"):
        target = bindir / name
        _shutil.copy2(real, target)
        target.chmod(0o755)
    return bindir


def test_probe_order_tries_python3_first_off_windows(tmp_path):
    """P2 (2026-07-31 corp report): off Windows, python3 first is correct and unchanged -
    it is the real interpreter there, not a Store stub."""
    bindir = _fake_interpreter_bin_dir(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proc = _run_with_env(proj, {"OS": ""}, path_prefix=bindir)
    assert proc.returncode == 0
    cache = proj / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8").strip() == "python3"


def test_probe_order_skips_python3_first_on_windows(tmp_path):
    """P2: with OS=Windows_NT (set by Windows itself, inherited into Git Bash), python3
    - the likely Store-stub name there - must not be the first one tried."""
    bindir = _fake_interpreter_bin_dir(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proc = _run_with_env(proj, {"OS": "Windows_NT"}, path_prefix=bindir)
    assert proc.returncode == 0
    cache = proj / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8").strip() == "python"


# --- CLAUDE_PLUGIN_ROOT vs CLAUDE_PROJECT_DIR: project state must never resolve under
# the plugin's own install directory (2026-08-13 live report) -------------------------
#
# team-preferences.json, the interpreter cache, the fan-out lock and the cold-start cache
# are all per-PROJECT state (install_helper.py's own write_guard_interpreter_cache()
# writes .guard-interpreter under the project directory, never a plugin install
# directory) - but were resolved via the same CLAUDE_PLUGIN_ROOT-first root as
# DAEMON_CLIENT (correct for THAT one case: bash_hook_dispatcher.py is a file the plugin
# itself ships). In plugin-install mode, whenever CLAUDE_PLUGIN_ROOT happened to be set
# in the hook's own process, that conflation pointed all four project-state paths at the
# plugin's own directory instead of the project's - confirmed live: a project's
# team-preferences.json had "guard_daemon": true recorded, but the daemon never
# activated, because the hook was checking a team-preferences.json under the plugin's
# install path, which does not exist.


def test_interpreter_cache_resolves_under_project_dir_not_plugin_root(tmp_path):
    """The regression itself, reproduced directly: CLAUDE_PLUGIN_ROOT and
    CLAUDE_PROJECT_DIR point at two DIFFERENT directories - the interpreter cache must
    land under the project directory, never the plugin root."""
    plugin_dir = tmp_path / "plugin-install"
    plugin_dir.mkdir()
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proc = _run_with_env(proj, {"CLAUDE_PLUGIN_ROOT": str(plugin_dir)})
    assert proc.returncode == 0
    assert (proj / ".claude" / ".guard-interpreter").is_file()
    assert not (plugin_dir / ".claude").exists()  # never written under the plugin root


def test_guard_daemon_preference_resolves_under_project_dir_not_plugin_root(tmp_path):
    """The exact reported scenario: guard_daemon: true sits in the PROJECT's own
    team-preferences.json (never found if the hook looks under the plugin root instead) -
    a decoy team-preferences.json with the SAME key under the plugin root must be
    ignored, proving the check reads the project's copy, not the plugin's."""
    plugin_dir = tmp_path / "plugin-install"
    (plugin_dir / ".claude").mkdir(parents=True)
    (plugin_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )  # decoy - must never be read
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    dispatcher_target = proj / "bash_hook_dispatcher.py"
    dispatcher_target.write_text("", encoding="utf-8")
    env = {
        "CLAUDE_PROJECT_DIR": str(proj),
        "CLAUDE_PLUGIN_ROOT": str(plugin_dir),
        "PATH": __import__("os").environ["PATH"],
    }
    # No guard_daemon_client.py under either root, so [ -f "$DAEMON_CLIENT" ] is false and
    # the launcher falls through to its normal cold-start path either way - this proves
    # _prefs resolution doesn't crash/misbehave when pointed correctly, independent of
    # whether the daemon files themselves are present.
    proc = subprocess.run(
        ["sh", str(LAUNCHER), str(dispatcher_target)],
        input=PAYLOAD,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    # The interpreter cache (same _project_root as the prefs check) must still land under
    # the project directory, confirming _project_root - not the plugin-rooted $_root - is
    # what this whole code path actually used.
    assert (proj / ".claude" / ".guard-interpreter").is_file()


def test_staged_and_live_launchers_match_when_installed():
    """HARD FAILURE, never a skip (audit 2026-08-01).

    Both skip paths here hid real states: a missing live launcher means the guards do not start
    at all, and an unapplied interpreter-cache fix is exactly the pending-work case the sync net
    exists to surface. Skipping when the fix is unapplied makes the net go quiet at the one
    moment it has something to report.
    """
    assert LIVE_LAUNCHER.is_file(), (
        f"live launcher missing at {LIVE_LAUNCHER} - the guards cannot start without it"
    )
    live = LIVE_LAUNCHER.read_text(encoding="utf-8")
    assert live == LAUNCHER.read_text(encoding="utf-8"), (
        "staged launcher not yet applied - run: bash scripts/apply-guard-daemon.sh "
        "(supersedes apply-guard-interpreter-cache.sh as of ADR-014 - the staged launcher "
        "now carries the daemon-aware branch too, so applying it alone without the other "
        "two staged daemon files would leave a launcher that references files that don't "
        "exist yet; apply-guard-daemon.sh installs all three together)"
    )
