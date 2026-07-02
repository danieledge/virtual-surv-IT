"""
Behavioural tests for the always-on safety guards (.claude/hooks/).

These drive the hooks the way Claude Code does - a PreToolUse JSON payload on stdin,
exit 2 to block / exit 0 to allow - and assert the INTENDED behaviour. They do not
modify the hooks. Note the hooks themselves document that Bash command-string matching
is advisory (a strong default, not a sandbox), so these cover the cases the guards are
designed to handle, not exhaustive shell-bypass resistance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RAW_GUARD = _ROOT / ".claude" / "hooks" / "guard-raw-data.py"
_EXEC_GUARD = _ROOT / ".claude" / "hooks" / "guard-code-execution.py"

BLOCK = 2
ALLOW = 0


def _run(script: Path, payload: dict, env_extra: dict | None = None) -> int:
    """Pipe *payload* as PreToolUse JSON to *script*; return its exit code."""
    env = {k: v for k, v in os.environ.items() if k != "CST_ALLOW_EXEC"}
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


# --- guard-raw-data.py --------------------------------------------------------
# CLAUDE_PROJECT_DIR points at the repo so data/raw/ resolves; the substring marker
# also fires, so either control is enough to block.


def _raw_env() -> dict:
    return {"CLAUDE_PROJECT_DIR": str(_ROOT)}


def test_raw_guard_blocks_read_of_raw():
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Read", "tool_input": {"file_path": "data/raw/orders.jsonl"}},
        _raw_env(),
    )
    assert code == BLOCK


def test_raw_guard_blocks_grep_under_raw():
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "data/raw"}},
        _raw_env(),
    )
    assert code == BLOCK


def test_raw_guard_blocks_grep_glob_under_raw():
    # The Grep tool's glob filter is named 'glob' (the hook also still checks 'include').
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "glob": "data/raw/*.csv"}},
        _raw_env(),
    )
    assert code == BLOCK


def test_raw_guard_blocks_bash_touching_raw():
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Bash", "tool_input": {"command": "cat data/raw/orders.jsonl"}},
        _raw_env(),
    )
    assert code == BLOCK


def test_raw_guard_allows_masked_read():
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Read", "tool_input": {"file_path": "data/masked/orders.jsonl"}},
        _raw_env(),
    )
    assert code == ALLOW


def test_raw_guard_allows_synthetic_read():
    code = _run(
        _RAW_GUARD,
        {"tool_name": "Read", "tool_input": {"file_path": "data/synthetic/spoofing.jsonl"}},
        _raw_env(),
    )
    assert code == ALLOW


def test_raw_guard_ignores_out_of_scope_tool():
    code = _run(
        _RAW_GUARD, {"tool_name": "Write", "tool_input": {"file_path": "data/raw/x"}}, _raw_env()
    )
    assert code == ALLOW


def test_raw_guard_allows_malformed_payload():
    # Fail-open on garbage so a bad payload never bricks a session.
    proc = subprocess.run(
        [sys.executable, str(_RAW_GUARD)],
        input="not json",
        text=True,
        capture_output=True,
        env={**os.environ, **_raw_env()},
    )
    assert proc.returncode == ALLOW


# --- guard-code-execution.py --------------------------------------------------
# Use a tmp project dir with NO .claude/.exec-consent so execution is unauthorised,
# and CST_ALLOW_EXEC is scrubbed by _run().


@pytest.fixture()
def no_consent(tmp_path) -> dict:
    return {"CLAUDE_PROJECT_DIR": str(tmp_path)}


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def test_exec_guard_blocks_pytest(no_consent):
    assert _run(_EXEC_GUARD, _bash("pytest tests/"), no_consent) == BLOCK


def test_exec_guard_blocks_running_a_py_file(no_consent):
    assert _run(_EXEC_GUARD, _bash("python target_module.py"), no_consent) == BLOCK


def test_exec_guard_blocks_executing_a_script(no_consent):
    assert _run(_EXEC_GUARD, _bash("./run.sh"), no_consent) == BLOCK


def test_exec_guard_allows_team_scripts(no_consent):
    assert _run(_EXEC_GUARD, _bash("python -m scripts.ingest data/raw"), no_consent) == ALLOW


def test_exec_guard_allows_static_analysers(no_consent):
    assert _run(_EXEC_GUARD, _bash("ruff check scripts/"), no_consent) == ALLOW
    assert _run(_EXEC_GUARD, _bash("git diff --stat"), no_consent) == ALLOW


def test_exec_guard_ignores_non_bash_tool(no_consent):
    assert (
        _run(_EXEC_GUARD, {"tool_name": "Read", "tool_input": {"file_path": "x.py"}}, no_consent)
        == ALLOW
    )


def test_exec_guard_allows_when_env_consent_set(no_consent):
    # The hard override: human-set CST_ALLOW_EXEC permits execution.
    env = {**no_consent, "CST_ALLOW_EXEC": "1"}
    assert _run(_EXEC_GUARD, _bash("pytest tests/"), env) == ALLOW


def test_exec_guard_allows_with_consent_marker(tmp_path):
    # The convenient path: a .claude/.exec-consent marker in the project dir.
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".exec-consent").write_text("ok")
    assert _run(_EXEC_GUARD, _bash("pytest tests/"), {"CLAUDE_PROJECT_DIR": str(tmp_path)}) == ALLOW


# --- ADR-002 Tier-1 hardening: harder bypasses now blocked --------------------


def test_exec_guard_blocks_python_dash_c(no_consent):
    # Inline code execution was previously whitelisted by an explicit -c carve-out.
    assert _run(_EXEC_GUARD, _bash("python -c \"import os;os.system('x')\""), no_consent) == BLOCK


def test_exec_guard_blocks_shell_dash_c(no_consent):
    assert _run(_EXEC_GUARD, _bash('bash -c "echo hi"'), no_consent) == BLOCK
    assert _run(_EXEC_GUARD, _bash('sh -c "rm x"'), no_consent) == BLOCK


def test_exec_guard_blocks_node_eval(no_consent):
    assert _run(_EXEC_GUARD, _bash('node -e "process.exit(0)"'), no_consent) == BLOCK


def test_exec_guard_blocks_versioned_python_file(no_consent):
    # python3.11 broke the old `python3?\s` anchor and slipped past.
    assert _run(_EXEC_GUARD, _bash("python3.11 evil.py"), no_consent) == BLOCK


def test_exec_guard_blocks_task_runners(no_consent):
    assert _run(_EXEC_GUARD, _bash("uv run python app.py"), no_consent) == BLOCK
    assert _run(_EXEC_GUARD, _bash("make test"), no_consent) == BLOCK


def test_exec_guard_blocks_chained_after_allowed_segment(no_consent):
    # The headline fix: an allow-listed segment must not wave through a blocked one chained after.
    assert (
        _run(_EXEC_GUARD, _bash("python -m scripts.render_html x.md && pytest"), no_consent)
        == BLOCK
    )
    assert _run(_EXEC_GUARD, _bash('echo "scripts."; python evil.py'), no_consent) == BLOCK


def test_exec_guard_allows_benign_chain(no_consent):
    # Chaining only non-executing/allowed segments stays allowed.
    assert _run(_EXEC_GUARD, _bash("git diff --stat && ruff check scripts/"), no_consent) == ALLOW


# --- Crash paths fail CLOSED (setup audit 2026-07-01) --------------------------
# An uncaught exception used to exit 1, which Claude Code treats as NON-blocking -
# the action proceeded and the gate was silently disarmed. The guards now wrap
# main() and exit 2 on any unexpected crash. Valid-JSON-but-not-a-dict payloads
# (e.g. a bare list) are the cheapest way to reach those paths.


def _pipe_raw_stdin(script: Path, stdin: str, env_extra: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        text=True,
        capture_output=True,
        env={**{k: v for k, v in os.environ.items() if k != "CST_ALLOW_EXEC"}, **env_extra},
    )
    return proc.returncode


def test_raw_guard_blocks_non_dict_payload():
    # Valid JSON, wrong shape -> payload.get crashes -> must fail closed, not proceed.
    assert _pipe_raw_stdin(_RAW_GUARD, "[]", _raw_env()) == BLOCK


def test_exec_guard_blocks_non_dict_payload(tmp_path):
    assert _pipe_raw_stdin(_EXEC_GUARD, '"x"', {"CLAUDE_PROJECT_DIR": str(tmp_path)}) == BLOCK


def test_exec_guard_allows_malformed_payload(tmp_path):
    # NOT-JSON stays deliberately fail-open (documented "never brick a session" carve-out);
    # only unexpected crashes fail closed.
    assert _pipe_raw_stdin(_EXEC_GUARD, "not json", {"CLAUDE_PROJECT_DIR": str(tmp_path)}) == ALLOW
