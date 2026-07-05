"""Regression tests for the ADR-002 recs 10-13 guard hardening.

Driven the way Claude Code drives the hooks: a PreToolUse JSON payload on stdin,
exit 2 = block, exit 0 = allow. Covers the false positives that were fixed and the
bypass classes that were closed, without asserting exhaustive shell-bypass resistance
(the guards remain lexical/advisory by design - see ADR-002).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / ".claude" / "hooks" / "guard-raw-data.py"
_EXEC = _ROOT / ".claude" / "hooks" / "guard-code-execution.py"
_CONSENT = _ROOT / ".claude" / "hooks" / "guard-consent-writes.py"

BLOCK, ALLOW = 2, 0


def _run(script: Path, payload: dict, drop: str, env_extra: dict | None = None) -> int:
    env = {k: v for k, v in os.environ.items() if k != drop}
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    return proc.returncode


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


# --- exec guard: pytest anchoring + broader runners ----------------------------


def _exec(cmd: str, tmp_path) -> int:
    return _run(_EXEC, _bash(cmd), "CST_ALLOW_EXEC", {"CLAUDE_PROJECT_DIR": str(tmp_path)})


def test_pytest_in_prose_is_not_blocked(tmp_path):
    # rec 11: the word inside a commit message must not read as the test runner.
    assert _exec('git commit -m "add pytest coverage for the export bug"', tmp_path) == ALLOW


def test_real_pytest_still_blocked(tmp_path):
    assert _exec("pytest tests/", tmp_path) == BLOCK


def test_env_prefixed_pytest_still_blocked(tmp_path):
    assert _exec("PYTHONPATH=. pytest tests/", tmp_path) == BLOCK


def test_broader_runners_blocked(tmp_path):
    for cmd in ("cargo run", "cargo test", "swift run", "bundle exec rspec", "jest", "vitest"):
        assert _exec(cmd, tmp_path) == BLOCK, cmd


def test_team_scripts_and_analysers_still_allowed(tmp_path):
    assert _exec("python -m scripts.ingest data/raw", tmp_path) == ALLOW
    assert _exec("ruff check scripts/", tmp_path) == ALLOW


# --- consent guard: jq/git read-only allowed, mutations blocked ----------------


def _consent(cmd: str) -> int:
    return _run(_CONSENT, _bash(cmd), "CST_ALLOW_CONFIG_EDIT")


def test_readonly_jq_on_settings_allowed():
    # rec 11: a read-only query on config is not a write.
    assert _consent("jq '.permissions' .claude/settings.json") == ALLOW


def test_readonly_git_on_protected_allowed():
    assert _consent("git check-ignore .claude/.exec-consent") == ALLOW
    assert _consent("git diff .claude/settings.json") == ALLOW


def test_mutating_git_on_settings_blocked():
    # git checkout/restore can revert the protected file - must NOT be waved through.
    assert _consent("git checkout .claude/settings.json") == BLOCK


def test_find_exec_on_settings_blocked():
    # rec 12: find ... -exec sed -i mutates through the safe `find` verb - now blocked.
    assert _consent("find .claude/settings.json -exec sed -i s/deny/allow/ {} ;") == BLOCK


def test_readonly_find_on_settings_still_allowed():
    assert _consent("find .claude -name settings.json") == ALLOW


# --- raw guard: no-trailing-slash + case-fold markers --------------------------


def _raw(cmd: str) -> int:
    return _run(_RAW, _bash(cmd), "X", {"CLAUDE_PROJECT_DIR": str(_ROOT)})


def test_raw_no_trailing_slash_blocked():
    # rec 12: `cd data/raw && ...` carries no trailing slash - the fixed markers missed it.
    assert _raw("cd data/raw && cat orders.jsonl") == BLOCK


def test_raw_case_folded_marker_blocked():
    assert _raw("cat DATA/RAW/orders.jsonl") == BLOCK


def test_raw_unrelated_path_not_blocked():
    # The lookbehind keeps the marker off unrelated paths.
    assert _raw("cat metadata/rawlog/summary.txt") == ALLOW
