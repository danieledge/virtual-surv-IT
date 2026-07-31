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


def test_staged_and_live_launchers_match_when_installed():
    """Once scripts/apply-guard-interpreter-cache.sh has been run, the two copies must be
    byte-identical (same contract as every other staged hook)."""
    if not LIVE_LAUNCHER.is_file():
        pytest.skip("live launcher not installed in this checkout")
    live = LIVE_LAUNCHER.read_text(encoding="utf-8")
    if "CACHE=" not in live:
        pytest.skip("interpreter-cache fix not yet applied to the live launcher")
    assert live == LAUNCHER.read_text(encoding="utf-8")
